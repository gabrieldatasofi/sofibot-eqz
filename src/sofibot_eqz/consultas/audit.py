"""Record of functionality 2: who asked what and how it ended. Never the values returned.

SQLite in the service's own folder (SOFIBOT_QUERY_DATA, /app/consultas in Docker), apart from
the Gold login, which stays read-only. Two tables:

- consultas: one row per query to SQL Server (user, table, measures, dimensions, filters,
  period, rows returned, duration, result: correcta | rechazada | error, reason);
- preguntas: one row per question, sent by whoever asked it or by an agent acting for them
  (outcome: respondida | no_disponible | ambigua | rechazada | error). Its text is kept only
  with SOFIBOT_QUERY_STORE_QUESTIONS=1, and erased after SOFIBOT_QUERY_QUESTION_DAYS days.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import csv
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .. import config

OUTCOMES = ("respondida", "no_disponible", "ambigua", "rechazada", "error")
CHANNELS = ("api", "portal", "mcp")
SCHEMA = """
CREATE TABLE IF NOT EXISTS consultas (
    id TEXT PRIMARY KEY, fecha TEXT NOT NULL, usuario TEXT NOT NULL, roles TEXT NOT NULL, canal TEXT NOT NULL,
    pregunta_id TEXT, tabla TEXT NOT NULL, medidas TEXT NOT NULL, dimensiones TEXT NOT NULL, filtros TEXT NOT NULL,
    periodo TEXT, filas INTEGER, duracion_ms INTEGER, resultado TEXT NOT NULL, motivo TEXT);
CREATE TABLE IF NOT EXISTS preguntas (
    id TEXT PRIMARY KEY, fecha TEXT NOT NULL, usuario TEXT NOT NULL, canal TEXT NOT NULL, texto TEXT,
    desenlace TEXT NOT NULL, motivo TEXT, consultas TEXT NOT NULL, modelo TEXT);
"""


def data_dir() -> Path:
    return Path(os.environ.get("SOFIBOT_QUERY_DATA", config.HOME / "consultas"))


def _connect() -> sqlite3.Connection:
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(folder / "registro.sqlite", timeout=10)
    connection.executescript(SCHEMA)
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_query(*, user: str, roles, channel: str, question_id: str | None, table: str, measures, dimensions,
                 filters, period, rows: int | None, duration_ms: int, result: str, reason: str = "") -> str:
    identifier = uuid.uuid4().hex
    with closing(_connect()) as connection, connection:
        connection.execute(
            "INSERT INTO consultas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (identifier, _now(), user, ",".join(roles), channel, question_id, table, json.dumps(measures),
             json.dumps(dimensions), json.dumps(filters, ensure_ascii=False), json.dumps(period), rows, duration_ms,
             result, reason[:500]))
    return identifier


def record_question(*, user: str, channel: str, outcome: str, question: str = "", reason: str = "",
                    query_ids=(), model: str = "", question_id: str | None = None) -> str:
    identifier = question_id or uuid.uuid4().hex
    keep_text = os.environ.get("SOFIBOT_QUERY_STORE_QUESTIONS") == "1"
    days = int(os.environ.get("SOFIBOT_QUERY_QUESTION_DAYS", "90"))
    with closing(_connect()) as connection, connection:
        connection.execute("INSERT OR REPLACE INTO preguntas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (identifier, _now(), user, channel, question[:2000] if keep_text and question else None,
                            outcome, reason[:500], json.dumps(list(query_ids)), model[:100]))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        connection.execute("UPDATE preguntas SET texto = NULL WHERE fecha < ? AND texto IS NOT NULL", (cutoff,))
    return identifier


def export(table: str, path: Path) -> int:
    """Write one of the two tables to CSV (for a usage report); returns the number of rows."""
    if table not in ("consultas", "preguntas"):
        raise ValueError("table must be consultas or preguntas")
    with closing(_connect()) as connection:
        cursor = connection.execute(f"SELECT * FROM {table} ORDER BY fecha")
        columns = [c[0] for c in cursor.description]
        rows = cursor.fetchall()
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(columns)
        writer.writerows(rows)
    return len(rows)

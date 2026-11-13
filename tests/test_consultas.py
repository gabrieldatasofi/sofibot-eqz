"""Functionality 2 (consultas/): catalog, SQL building, permissions and record, with a fake database."""
from datetime import date
from decimal import Decimal
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from sofibot_eqz.consultas import audit, catalog, query

CATALOG = {"tables": {
    "gold.month_store": {
        "description": "Ventas mensuales por tienda", "period": "month",
        "dimensions": {"mes": {"column": "month"}, "tienda": {"column": "store_name", "synonyms": ["local"]}},
        "measures": {"ventas": {"sum": "sales_eur", "format": "eur"},
                     "margen_pct": {"ratio": ["profit_eur", "sales_eur"], "format": "percent"},
                     "tiendas": {"distinct": "store_name", "format": "integer"}},
        "rules": ["No sumar con gold.products"]},
    "gold.salaries": {"measures": {"sueldo": {"sum": "salary"}}},
}}
CONTRACT = {"schema": "gold", "tables": {
    "gold.month_store": {"columns": [{"name": c} for c in ("month", "store_name", "sales_eur", "profit_eur")]},
    "gold.salaries": {"columns": [{"name": "salary"}]}}}


@pytest.fixture
def entries(folders):
    (folders / "reports" / "catalogo.json").write_text(json.dumps(CATALOG), encoding="utf-8")
    (folders / "reports" / "gold_schema.json").write_text(json.dumps(CONTRACT), encoding="utf-8")
    (folders / "reports" / "permisos.json").write_text(json.dumps({"roles": {"Tiendas": ["gold.month_store"],
                                                                             "Direccion": ["*"]}}))
    return catalog.load()


# --- Catalog ---------------------------------------------------------------------------

def test_catalog_loads_and_matches_the_schema(entries):
    assert set(entries) == {"gold.month_store", "gold.salaries"}
    assert entries["gold.month_store"]["measures"]["margen_pct"]["columns"] == ["profit_eur", "sales_eur"]
    assert catalog.problems_against(entries, CONTRACT) == []
    broken = {"tables": {"gold.month_store": {"columns": [{"name": "month"}]}}}
    assert any("sales_eur" in p for p in catalog.problems_against(entries, broken))
    assert set(catalog.for_tables(entries, {"gold.month_store"})) == {"gold.month_store"}


@pytest.mark.parametrize("spec", [
    {"measures": {}},
    {"measures": {"Ventas": {"sum": "x"}}},
    {"measures": {"v": {"sum": "x", "distinct": "y"}}},
    {"measures": {"v": {"ratio": ["x"]}}},
    {"measures": {"v": {"sum": "x; DROP TABLE t"}}},
    {"measures": {"v": {"sum": "x", "format": "money"}}},
    {"measures": {"v": {"sum": "x"}}, "dimensions": {"v": {"column": "x"}}},
])
def test_catalog_rejects_bad_entries(folders, spec):
    path = folders / "reports" / "catalogo.json"
    path.write_text(json.dumps({"tables": {"gold.t": spec}}))
    with pytest.raises(catalog.CatalogError):
        catalog.load(path)


# --- SQL -------------------------------------------------------------------------------

def request(**fields):
    return query.QueryRequest.model_validate({"table": "gold.month_store", "measures": ["ventas"], **fields})


def test_sql_is_built_from_the_catalog_with_parameters(entries):
    sql, params, columns = query.build(entries, request(
        measures=["ventas", "margen_pct", "tiendas"], dimensions=["tienda"],
        filters=[{"dimension": "tienda", "values": ["Madrid", "Bilbao'; DROP TABLE x--"]}],
        period={"from": "2025-11", "to": "2026-01"}, order={"by": "ventas"}, limit=10), max_rows=1000)
    assert sql == ("SELECT TOP (?) [store_name] AS [tienda], SUM([sales_eur]) AS [ventas], "
                   "CAST(SUM([profit_eur]) AS decimal(38, 10)) / NULLIF(SUM([sales_eur]), 0) AS [margen_pct], "
                   "COUNT(DISTINCT [store_name]) AS [tiendas] FROM [gold].[month_store] "
                   "WHERE [month] >= ? AND [month] < ? AND [store_name] IN (?, ?) "
                   "GROUP BY [store_name] ORDER BY [ventas] DESC")
    assert params == [11, date(2025, 11, 1), date(2026, 2, 1), "Madrid", "Bilbao'; DROP TABLE x--"]
    assert columns == ["tienda", "ventas", "margen_pct", "tiendas"]


def test_totals_and_row_limit(entries):
    sql, params, _ = query.build(entries, request(limit=5000), max_rows=1000)
    assert sql == "SELECT TOP (?) SUM([sales_eur]) AS [ventas] FROM [gold].[month_store]" and params == [1001]


@pytest.mark.parametrize("fields", [
    {"table": "gold.salaries"},                       # not in this user's catalog
    {"measures": ["sueldo"]},
    {"dimensions": ["pais"]},
    {"filters": [{"dimension": "pais", "values": ["ES"]}]},
    {"period": {"from": "2026-13", "to": "2026-12"}},
    {"period": {"from": "2026-05", "to": "2026-01"}},
    {"order": {"by": "margen_pct"}},
    {"dimensions": ["tienda", "tienda"]},
])
def test_invalid_requests(entries, fields):
    visible = {"gold.month_store": entries["gold.month_store"]}
    with pytest.raises(query.QueryError):
        query.build(visible, request(**fields), max_rows=1000)


def test_requests_accept_no_sql_or_unknown_fields():
    with pytest.raises(ValueError):
        query.QueryRequest.model_validate({"table": "gold.t", "measures": ["v"], "sql": "SELECT 1"})


# --- API -------------------------------------------------------------------------------

class FakeGold:
    calls = []

    def query(self, sql, params):
        FakeGold.calls.append((sql, params))
        return ["tienda", "ventas"], [("Madrid", Decimal("1200.50")), ("Bilbao", None), ("Vigo", Decimal("3"))]


@pytest.fixture
def service(entries, monkeypatch, entra_token):
    from sofibot_eqz.consultas import server

    monkeypatch.setenv("SOFIBOT_QUERY_ENABLED", "1")
    monkeypatch.setenv("SOFIBOT_QUERY_MAX_ROWS", "2")
    monkeypatch.setattr(server, "Gold", FakeGold)
    server._recent.clear()
    FakeGold.calls = []
    return TestClient(server.app)


def records(folders, table):
    with sqlite3.connect(folders / "consultas" / "registro.sqlite") as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def test_query_with_permissions_limits_and_record(service, folders, entra_token):
    user = {"Authorization": entra_token(["Sofibot.Consultas", "Tiendas"], email="laura@eqz.test"),
            "X-Sofibot-Channel": "portal"}
    tables = service.get("/api/query/catalog", headers=user).json()["tables"]
    assert list(tables) == ["gold.month_store"] and "column" not in json.dumps(tables)
    body = {"table": "gold.month_store", "measures": ["ventas"], "dimensions": ["tienda"],
            "filters": [{"dimension": "tienda", "values": ["Madrid"]}], "period": {"from": "2026-01", "to": "2026-03"}}
    result = service.post("/api/query", headers=user, json=body).json()
    assert result["rows"] == [["Madrid", 1200.5], ["Bilbao", None]] and result["truncated"] is True
    assert service.post("/api/query", headers=user, json={**body, "table": "gold.salaries",
                                                           "measures": ["sueldo"]}).status_code == 400
    service.post("/api/query/outcome", headers=user, json={
        "outcome": "no_disponible", "question": "¿Cuál es el sueldo del jefe?", "reason": "No hay sueldos"})
    logged = records(folders, "consultas")
    assert [(r["usuario"], r["canal"], r["tabla"], r["resultado"], r["filas"]) for r in logged] == [
        ("laura@eqz.test", "portal", "gold.month_store", "correcta", 2),
        ("laura@eqz.test", "portal", "gold.salaries", "rechazada", None)]
    assert "1200" not in json.dumps(logged)          # values are never recorded
    question, = records(folders, "preguntas")
    assert question["desenlace"] == "no_disponible" and question["texto"] is None  # text off by default


def test_question_text_only_when_allowed(service, folders, entra_token, monkeypatch):
    monkeypatch.setenv("SOFIBOT_QUERY_STORE_QUESTIONS", "1")
    user = {"Authorization": entra_token(["Sofibot.Consultas", "Tiendas"])}
    service.post("/api/query/outcome", headers=user, json={"outcome": "respondida", "question": "Ventas de marzo"})
    assert records(folders, "preguntas")[0]["texto"] == "Ventas de marzo"
    assert service.post("/api/query/outcome", headers=user, json={"outcome": "quizas"}).status_code == 400


def test_query_needs_the_role_the_switch_and_a_user_token(service, entra_token, monkeypatch):
    body = {"table": "gold.month_store", "measures": ["ventas"]}
    assert service.post("/api/query", json=body).status_code == 401
    assert service.post("/api/query", json=body, headers={"Authorization": entra_token(["Tiendas"])}).status_code == 403
    no_user = entra_token(["Sofibot.Consultas", "Direccion"], scp=None)
    assert service.post("/api/query", json=body, headers={"Authorization": no_user}).status_code == 401
    monkeypatch.setenv("SOFIBOT_QUERY_ENABLED", "0")
    assert service.post("/api/query", json=body, headers={"Authorization": entra_token(["Sofibot.Consultas"])}).status_code == 503
    assert FakeGold.calls == []


def test_queries_per_minute(service, entra_token, monkeypatch):
    monkeypatch.setenv("SOFIBOT_QUERY_PER_MINUTE", "2")
    user = {"Authorization": entra_token(["Sofibot.Consultas", "Direccion"])}
    body = {"table": "gold.salaries", "measures": ["sueldo"]}
    assert [service.post("/api/query", headers=user, json=body).status_code for _ in range(3)] == [200, 200, 429]


def test_database_errors_are_recorded_without_their_message(service, folders, entra_token, monkeypatch):
    class Broken:
        def query(self, sql, params):
            raise RuntimeError("Conversion failed when converting the value 'secreto'")

    from sofibot_eqz.consultas import server

    monkeypatch.setattr(server, "Gold", Broken)
    user = {"Authorization": entra_token(["Sofibot.Consultas", "Tiendas"])}
    response = service.post("/api/query", headers=user, json={"table": "gold.month_store", "measures": ["ventas"]})
    assert response.status_code == 502 and "secreto" not in response.text
    logged, = records(folders, "consultas")
    assert logged["resultado"] == "error" and logged["motivo"] == "RuntimeError"


def test_cli_catalog_and_export(entries, folders, capsys):
    from sofibot_eqz import cli

    assert cli.main(["catalog"]) == 0 and "gold.month_store" in capsys.readouterr().out
    audit.record_query(user="a", roles=(), channel="api", question_id=None, table="gold.t", measures=["v"],
                       dimensions=[], filters=[], period=None, rows=1, duration_ms=3, result="correcta")
    out = folders / "registro.csv"
    assert cli.main(["consultas-registro", "consultas", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8-sig").splitlines()[0].startswith("id;fecha;usuario")

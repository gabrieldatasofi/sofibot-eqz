"""Functionality 1, report drafts: what the report-code API (/api/code), its MCP server and the
review page work on (docs/10-api-informes.md).

An author's AI assistant reads the Gold schema contract and writes report projects
(report.json + generate.py) here, in the drafts folder (config.DRAFTS_DIR), never in reports/.
Nothing an author does runs a draft's code or opens the database: the check is static. A
reviewer (a person) builds a preview, looks at it and publishes the draft into reports/, or
rejects it with a comment. The AI never sees data (docs/06-seguridad.md).

Everyone acts as an identity (identity.py) and only on the Gold tables their roles allow
(`tables`: a set, or None for every table). A draft is visible to a caller only when its
tables are all allowed. Every action is recorded with who did it in <drafts>/registro.sqlite.

Status of each draft, in <drafts>/<slug>/.draft.json:

    draft --submit--> submitted --publish--> published
      ^                   |
      |                   +--reject--> rejected (with the reviewer's comment)
      +---- writing a file returns any draft to "draft" and discards its preview

No function returns data: only schema, code, names, statuses and who did what.
"""
import ast
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading

from . import config, projects
from .db import referenced_tables

FILE_NAME = re.compile(r"report\.json|[a-z_][a-z0-9_]*\.py")
STATUS_FILE = ".draft.json"
BACKUPS = ".anteriores"
REGISTRY = "registro.sqlite"
MAX_FILE_BYTES = 200_000
GUIDE = Path(__file__).resolve().parent / "report_guide.md"
_lock = threading.Lock()


class DraftError(Exception):
    """A refused request. The message is safe to return to the caller: it never holds data."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


API_MODES = ("off", "entra", "token")


def api_mode(env=os.environ) -> str:
    """SOFIBOT_CODE_API: off (default), entra (each author with their Microsoft account) or token
    (one shared SOFIBOT_API_TOKEN, for tests: nobody knows who did what). Unset with a token: token."""
    value = env.get("SOFIBOT_CODE_API", "").strip().lower()
    if not value:
        return "token" if env.get("SOFIBOT_API_TOKEN") else "off"
    if value not in API_MODES:
        raise DraftError(f"SOFIBOT_CODE_API must be one of {', '.join(API_MODES)}", 503)
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Who did what -------------------------------------------------------------------------

def _registry() -> sqlite3.Connection:
    config.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.DRAFTS_DIR / REGISTRY, timeout=10)
    connection.execute("CREATE TABLE IF NOT EXISTS eventos (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, "
                       "persona TEXT NOT NULL, operacion TEXT NOT NULL, informe TEXT NOT NULL, detalle TEXT NOT NULL)")
    return connection


def record(actor: str, operation: str, slug: str, detail: str = "") -> None:
    with closing(_registry()) as connection, connection:
        connection.execute("INSERT INTO eventos (fecha, persona, operacion, informe, detalle) VALUES (?, ?, ?, ?, ?)",
                           (_now(), actor or "desconocido", operation, slug, detail[:500]))


def history(slug: str) -> list[dict]:
    with closing(_registry()) as connection:
        rows = connection.execute("SELECT fecha, persona, operacion, detalle FROM eventos WHERE informe = ? ORDER BY id",
                                  (slug,)).fetchall()
    return [{"at": at, "who": who, "operation": operation, "detail": detail} for at, who, operation, detail in rows]


def events(limit: int = 1000) -> list[dict]:
    with closing(_registry()) as connection:
        rows = connection.execute("SELECT fecha, persona, operacion, informe, detalle FROM eventos ORDER BY id DESC LIMIT ?",
                                  (limit,)).fetchall()
    return [{"at": a, "who": w, "operation": o, "slug": s, "detail": d} for a, w, o, s, d in rows]


# --- Schema -------------------------------------------------------------------------------

def _contract() -> dict | None:
    path = config.REPORTS_DIR / config.SCHEMA_FILE.name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise DraftError(f"{path.name} cannot be read: {exc}", 500) from exc


def _gold_schema(contract: dict | None) -> str:
    return (contract or {}).get("schema") or os.environ.get("SQLSERVER_GOLD_SCHEMA", "gold")


def _known_tables(contract: dict | None) -> set[str] | None:
    if not contract or not isinstance(contract.get("tables"), dict):
        return None
    return {name.casefold() for name in contract["tables"]}


def _allows(tables: set[str] | None, wanted) -> bool:
    return tables is None or {table.casefold() for table in wanted} <= tables


def describe_schema(tables: set[str] | None = None) -> dict:
    """The Gold schema contract (only the caller's tables) plus the report guide. No data."""
    contract = _contract()
    if contract is None:
        raise DraftError("reports/gold_schema.json does not exist yet: a person must run `sofibot schema`", 503)
    if tables is not None:
        contract = {**contract, "tables": {name: value for name, value in contract.get("tables", {}).items()
                                           if name.casefold() in tables}}
    return {**contract, "report_guide": GUIDE.read_text(encoding="utf-8")}


# --- Drafts -------------------------------------------------------------------------------

def _check_slug(slug: str) -> None:
    if not isinstance(slug, str) or not projects.SLUG.fullmatch(slug):
        raise DraftError("The slug must be lowercase letters, digits and single hyphens, e.g. ventas-tiendas")


def _declared(path: Path) -> list[str]:
    try:
        manifest = json.loads((path / "report.json").read_text(encoding="utf-8"))
        tables = manifest.get("tables") if isinstance(manifest, dict) else None
    except (OSError, ValueError):
        return []
    return [t for t in tables if isinstance(t, str)] if isinstance(tables, list) else []


def _draft(slug: str, tables: set[str] | None = None) -> Path:
    """A draft the caller may see: all its tables allowed. Otherwise it does not exist for them."""
    _check_slug(slug)
    path = config.DRAFTS_DIR / slug
    if not (path / "report.json").is_file() or not _allows(tables, _declared(path)):
        raise DraftError(f"Draft '{slug}' does not exist", 404)
    return path


def _read_status(path: Path) -> dict:
    try:
        return json.loads((path / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "draft"}


def _write_status(path: Path, status: str, **extra) -> dict:
    record_ = {**_read_status(path), "status": status, "updated_at": _now(), **extra}
    if status != "rejected":
        record_.pop("comment", None)
    (path / STATUS_FILE).write_text(json.dumps(record_, indent=2, ensure_ascii=False), encoding="utf-8")
    return record_


def _code_files(path: Path) -> list[str]:
    return sorted(item.name for item in path.iterdir() if item.is_file() and FILE_NAME.fullmatch(item.name))


def _summary(path: Path) -> dict:
    try:
        manifest = json.loads((path / "report.json").read_text(encoding="utf-8"))
        manifest = manifest if isinstance(manifest, dict) else {}
    except (OSError, ValueError):
        manifest = {}
    return {"slug": path.name, "name": manifest.get("name", ""), "description": manifest.get("description", ""),
            "tables": manifest.get("tables", []), **_read_status(path), "files": _code_files(path),
            "has_preview": preview_dir(path.name) is not None}


def list_drafts(tables: set[str] | None = None) -> list[dict]:
    if not config.DRAFTS_DIR.is_dir():
        return []
    return [_summary(path) for path in sorted(config.DRAFTS_DIR.iterdir())
            if path.is_dir() and projects.SLUG.fullmatch(path.name) and (path / "report.json").is_file()
            and _allows(tables, _declared(path))]


def draft_status(slug: str, tables: set[str] | None = None) -> dict:
    return {**_summary(_draft(slug, tables)), "history": history(slug)}


def list_reports(tables: set[str] | None = None) -> list[dict]:
    """Published report projects in reports/ (code only) whose tables the caller may use."""
    found = []
    for slug, path in projects.projects().items():
        try:
            manifest = projects.manifest(path)
        except projects.ProjectError:
            manifest = {"name": slug}
        report_tables = manifest.get("tables", [])
        if tables is not None and not (report_tables and _allows(tables, report_tables)):
            continue
        found.append({"slug": slug, "name": manifest.get("name", slug), "description": manifest.get("description", ""),
                      "tables": report_tables, "has_draft": (config.DRAFTS_DIR / slug).is_dir()})
    return found


def create_draft(slug: str, name: str = "", table: str = "", description: str = "", from_report: bool = False,
                 actor: str = "", tables: set[str] | None = None) -> dict:
    """A new draft from the template (name + main table) or a copy of a published report (from_report)."""
    _check_slug(slug)
    with _lock:
        target = config.DRAFTS_DIR / slug
        if target.exists():
            raise DraftError(f"Draft '{slug}' already exists", 409)
        published = projects.projects().get(slug)
        if from_report:
            if published is None or not _allows(tables, _declared(published) or ["?"]):
                raise DraftError(f"There is no published report '{slug}' to copy", 404)
            target.mkdir(parents=True)
            for source in [published / "report.json", *published.glob("*.py")]:
                if FILE_NAME.fullmatch(source.name):
                    shutil.copyfile(source, target / source.name)
        else:
            if published is not None:
                raise DraftError(f"A published report is called '{slug}': use from_report to edit it, or another slug", 409)
            if not isinstance(name, str) or not name.strip():
                raise DraftError("name cannot be empty")
            known = _known_tables(_contract())
            if (known is not None and str(table).casefold() not in known) or not _allows(tables, [str(table)]):
                raise DraftError(f"'{table}' is not one of your tables in the schema contract: use one from describe_schema")
            config.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
            try:
                projects.create(slug, name.strip(), table, description, root=config.DRAFTS_DIR)
            except projects.ProjectError as exc:
                raise DraftError(str(exc)) from exc
        _write_status(target, "draft", created_at=_now(), created_by=actor,
                      source="report" if from_report else "template")
        record(actor, "crear", slug, "copia del informe publicado" if from_report else f"plantilla, {table}")
    return _summary(target)


def _file(slug: str, name: str, tables: set[str] | None) -> Path:
    if not isinstance(name, str) or not FILE_NAME.fullmatch(name):
        raise DraftError("Only report.json and Python files with lowercase names (e.g. generate.py) are allowed")
    return _draft(slug, tables) / name


def read_file(slug: str, name: str, tables: set[str] | None = None) -> dict:
    path = _file(slug, name, tables)
    if not path.is_file():
        raise DraftError(f"{name} does not exist in draft '{slug}'", 404)
    return {"slug": slug, "name": name, "content": path.read_text(encoding="utf-8")}


def write_file(slug: str, name: str, content: str, actor: str = "", tables: set[str] | None = None) -> dict:
    """Replace (or add) a file of a draft. Any change returns the draft to "draft" and drops its preview."""
    path = _file(slug, name, tables)
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise DraftError(f"The content must be text of at most {MAX_FILE_BYTES} bytes")
    if name == "report.json":
        try:
            manifest = json.loads(content)
        except ValueError as exc:
            raise DraftError(f"report.json is not valid JSON: {exc}") from exc
        if not isinstance(manifest, dict) or manifest.get("slug") != slug:
            raise DraftError(f'report.json must be an object whose "slug" is "{slug}"')
        declared = manifest.get("tables") if isinstance(manifest.get("tables"), list) else []
        if not _allows(tables, [t for t in declared if isinstance(t, str)]):
            raise DraftError('report.json lists tables you have no access to in "tables"', 403)
    with _lock:
        # Editing a submitted draft withdraws it: the reviewer must approve the final code.
        path.write_text(content, encoding="utf-8")
        _discard_preview(slug)
        _write_status(path.parent, "draft")
        record(actor, "escribir", slug, name)
    return {"slug": slug, "name": name, "bytes": len(content.encode("utf-8")), "status": "draft"}


def delete_draft(slug: str, actor: str = "", tables: set[str] | None = None) -> dict:
    path = _draft(slug, tables)
    with _lock:
        shutil.rmtree(path)
        _discard_preview(slug)
        record(actor, "borrar", slug)
    return {"deleted": slug}


def check_draft(slug: str, tables: set[str] | None = None) -> dict:
    """Static check: report.json, Python syntax and the Gold tables named in the code.

    Runs no code and opens no database, so it cannot prove that the queries work: the
    reviewer's preview does that.
    """
    path = _draft(slug, tables)
    problems = []
    try:
        manifest = projects.manifest(path)
    except projects.ProjectError as exc:
        manifest = {}
        problems.append(str(exc).replace(str(path), slug))
    declared = set(manifest.get("tables") or [])
    if manifest and not declared:
        problems.append('report.json must list in "tables" every Gold table the report reads')
    if not (path / "generate.py").is_file():
        problems.append("generate.py is missing")
    contract = _contract()
    known = _known_tables(contract)
    referenced = set()
    for name in _code_files(path):
        if not name.endswith(".py"):
            continue
        source = (path / name).read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, name)
        except SyntaxError as exc:
            problems.append(f"{name}, line {exc.lineno}: syntax error: {exc.msg}")
            continue
        # Table names live in the code's strings (SQL, TABLE = "gold.x"); `gold.query(...)` is Python.
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                referenced |= referenced_tables(node.value, _gold_schema(contract))
    if undeclared := sorted(referenced - declared):
        problems.append(f"The code reads {', '.join(undeclared)}, which report.json does not list in \"tables\"")
    if known is None:
        problems.append("reports/gold_schema.json does not exist: the tables could not be checked")
    elif unknown := sorted((declared | referenced) - known):
        problems.append(f"Not in the schema contract: {', '.join(unknown)}")
    if tables is not None and (forbidden := sorted((declared | referenced) - tables - {"*"})):
        problems.append(f"You have no access to: {', '.join(forbidden)}")
    return {"slug": slug, "ok": not problems, "problems": problems, "tables": sorted(declared),
            "note": "Static check: no code was run and no database was opened."}


def submit_draft(slug: str, actor: str = "", tables: set[str] | None = None) -> dict:
    """Check, then mark the draft for review. A reviewer previews and publishes it; nothing is built here."""
    checked = check_draft(slug, tables)
    if not checked["ok"]:
        return {**checked, "submitted": False}
    with _lock:
        status = _write_status(_draft(slug, tables), "submitted", submitted_at=_now(), submitted_by=actor)
        record(actor, "enviar", slug)
    return {**checked, "submitted": True, "status": status["status"]}


# --- Review (a person) --------------------------------------------------------------------

def _previews() -> Path:
    return config.OUTPUT_DIR / ".previews"


def preview_dir(slug: str) -> Path | None:
    path = _previews() / slug
    return path if path.is_dir() else None


def _error_file(slug: str) -> Path:
    return _previews() / f"{slug}.error.txt"


def preview_error(slug: str) -> str | None:
    """The end of the output of the last failed preview. It may contain real values: only for the
    review page (reviewers have access to the data), never for the report-code API."""
    path = _error_file(slug)
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def _discard_preview(slug: str) -> None:
    shutil.rmtree(_previews() / slug, ignore_errors=True)
    _error_file(slug).unlink(missing_ok=True)


def build_preview(slug: str, actor: str = "", tables: set[str] | None = None) -> dict:
    """Run a submitted draft against the database into a preview that only reviewers can open.

    A person's step (the reviewer's), like `sofibot build`: the result holds real data and is
    never returned to an AI assistant.
    """
    path = _draft(slug, tables)
    if _read_status(path).get("status") != "submitted":
        raise DraftError(f"Draft '{slug}' is not submitted", 409)
    try:
        projects.run(path, _previews() / slug, capture=True)
    except projects.ProjectError as exc:
        _previews().mkdir(parents=True, exist_ok=True)
        _error_file(slug).write_text(exc.output.replace(str(path), slug) or str(exc), encoding="utf-8")
        record(actor, "vista previa fallida", slug)  # no detail here: the author's AI reads the history
        raise DraftError("La vista previa ha fallado: el error está debajo, en «Error de la vista previa»", 500) from exc
    _error_file(slug).unlink(missing_ok=True)
    with _lock:
        _write_status(path, "submitted", preview_at=_now(), preview_by=actor)
        record(actor, "vista previa", slug)
    return {"slug": slug, "preview": True}


def publish(slug: str, force: bool = False, actor: str = "", tables: set[str] | None = None,
            own_review: bool = True) -> dict:
    """Copy a submitted draft into reports/<slug> (a reviewer's step, after reading the code).

    With a preview, the previewed build becomes the published report at once; otherwise it is
    built at the next scheduled build or with `sofibot build <slug>`. own_review=False refuses
    a reviewer publishing their own submission. The previous code of a published report is
    kept in <drafts>/.anteriores/<slug>-<time>/.
    """
    path = _draft(slug, tables)
    with _lock:
        status = _read_status(path)
        if status.get("status") != "submitted" and not force:
            raise DraftError(f"Draft '{slug}' is '{status.get('status')}', not 'submitted'", 409)
        if not own_review and actor and actor == status.get("submitted_by"):
            raise DraftError("Another reviewer must publish a draft you submitted", 403)
        checked = check_draft(slug, tables)
        if not checked["ok"]:
            raise DraftError("The check fails: " + "; ".join(checked["problems"]), 409)
        target = config.REPORTS_DIR / slug
        backup = None
        if target.exists():
            backup = config.DRAFTS_DIR / BACKUPS / f"{slug}-{datetime.now():%Y%m%d-%H%M%S}"
            backup.mkdir(parents=True)
            for old in target.iterdir():
                if old.is_file() and FILE_NAME.fullmatch(old.name):
                    shutil.copyfile(old, backup / old.name)
                    old.unlink()
        target.mkdir(parents=True, exist_ok=True)
        for name in _code_files(path):
            shutil.copyfile(path / name, target / name)
        preview = preview_dir(slug)
        if preview is not None:
            projects.replace(preview, config.OUTPUT_DIR / slug)
        _write_status(path, "published", published_at=_now(), published_by=actor)
        record(actor, "publicar", slug, "con la vista previa" if preview else "sin vista previa")
    return {"slug": slug, "status": "published", "built": preview is not None,
            "previous_code": str(backup) if backup else None}


def reject(slug: str, comment: str = "", actor: str = "", tables: set[str] | None = None) -> dict:
    path = _draft(slug, tables)
    with _lock:
        status = _write_status(path, "rejected", comment=str(comment)[:2000], rejected_by=actor)
        _discard_preview(slug)
        record(actor, "rechazar", slug, str(comment)[:500])
    return {"slug": slug, "status": status["status"], "comment": status.get("comment", "")}

"""Functionality 2 service: the query API (docs/11-consultas.md).

    GET  /api/query/catalog   what the caller may ask (their tables only)
    POST /api/query           run a structured query; returns the rows
    POST /api/query/outcome   record how a question ended (also when no query was run)

Every call carries the user's Entra ID access token and needs the Sofibot.Consultas role;
the tables come from reports/permisos.json, as in the portal. Off unless
SOFIBOT_QUERY_ENABLED=1. Runs as its own process and container, with its own SQL Server
login (read-only) and settings: it shares nothing with the portal but the sign-in rules.
"""
from collections import defaultdict, deque
import logging
import os
import threading
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .. import __version__, access, identity
from ..db import Gold
from . import audit, catalog as catalog_module
from .query import QueryError, QueryRequest, build, plain

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sofibot.consultas")
app = FastAPI(title="Sofibot consultas", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
_recent: dict[str, deque] = defaultdict(deque)
_recent_lock = threading.Lock()


def setting(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def caller(request: Request) -> identity.Identity:
    if os.environ.get("SOFIBOT_QUERY_ENABLED") != "1":
        raise HTTPException(503, "Queries are off (SOFIBOT_QUERY_ENABLED)")
    try:
        user = identity.from_bearer(request.headers.get("authorization", ""))
    except identity.IdentityError as exc:
        raise HTTPException(401, str(exc)) from exc
    if identity.ROLE_QUERY not in user.roles:
        raise HTTPException(403, f"Your account does not have the {identity.ROLE_QUERY} role")
    return user


def channel(request: Request) -> str:
    value = request.headers.get("x-sofibot-channel", "api").lower()
    return value if value in audit.CHANNELS else "api"


def throttle(user: identity.Identity) -> None:
    """At most SOFIBOT_QUERY_PER_MINUTE queries per user per minute."""
    limit, now = setting("SOFIBOT_QUERY_PER_MINUTE", 30), time.monotonic()
    with _recent_lock:
        recent = _recent[user.email]
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= limit:
            raise HTTPException(429, f"Too many queries: at most {limit} per minute")
        recent.append(now)


def user_catalog(user: identity.Identity) -> dict:
    """The catalog restricted to the user's tables (the rest does not exist for them)."""
    try:
        full = catalog_module.load()
    except catalog_module.CatalogError as exc:
        log.warning("Catalog: %s", exc)
        raise HTTPException(503, "The query catalog is not available") from exc
    tables = user.tables(access.load())
    return {name: spec for name, spec in full.items() if tables is None or name in tables}


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/query/catalog")
def query_catalog(user: identity.Identity = Depends(caller)):
    visible = user_catalog(user)
    return {"tables": catalog_module.for_tables(visible, None), "max_rows": setting("SOFIBOT_QUERY_MAX_ROWS", 1000),
            "request": QueryRequest.model_json_schema(by_alias=True),
            "outcomes": list(audit.OUTCOMES),
            "note": "Measures are sums, ratios of sums or distinct counts. Periods are whole months, YYYY-MM. "
                    "null means no data, not zero."}


@app.post("/api/query")
async def run_query(body: QueryRequest, request: Request, user: identity.Identity = Depends(caller)):
    throttle(user)
    visible = await run_in_threadpool(user_catalog, user)
    started = time.monotonic()
    summary = dict(user=user.email, roles=user.roles, channel=channel(request), question_id=body.question_id,
                   table=body.table.casefold(), measures=body.measures, dimensions=body.dimensions,
                   filters=[f.model_dump() for f in body.filters],
                   period=body.period.model_dump(by_alias=True) if body.period else None)
    max_rows = setting("SOFIBOT_QUERY_MAX_ROWS", 1000)
    try:
        sql, params, columns = build(visible, body, max_rows)
    except QueryError as exc:
        query_id = audit.record_query(**summary, rows=None, duration_ms=0, result="rechazada", reason=str(exc))
        raise HTTPException(400, {"message": str(exc), "query_id": query_id}) from exc
    limit = min(body.limit or max_rows, max_rows)
    try:
        _, rows = await run_in_threadpool(Gold().query, sql, params)
    except Exception as exc:  # SQL Server messages can quote values: only the error type is kept
        elapsed = int((time.monotonic() - started) * 1000)
        query_id = audit.record_query(**summary, rows=None, duration_ms=elapsed, result="error", reason=type(exc).__name__)
        log.exception("Query %s by %s on %s failed", query_id, user.email, summary["table"])
        raise HTTPException(502, {"message": "The database could not answer this query", "query_id": query_id}) from exc
    elapsed = int((time.monotonic() - started) * 1000)
    truncated = len(rows) > limit
    rows = rows[:limit]
    query_id = audit.record_query(**summary, rows=len(rows), duration_ms=elapsed, result="correcta")
    log.info("Query %s by %s on %s: %d rows in %d ms", query_id, user.email, summary["table"], len(rows), elapsed)
    spec = visible[summary["table"]]
    return {"query_id": query_id, "table": summary["table"], "columns": columns,
            "rows": [[plain(value) for value in row] for row in rows], "truncated": truncated,
            "period": summary["period"],
            "measures": {name: {"format": spec["measures"][name]["format"],
                                "description": spec["measures"][name]["description"]} for name in body.measures}}


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str
    question: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=500)
    query_ids: list[str] = Field(default_factory=list, max_length=50)
    question_id: str | None = Field(default=None, max_length=64)
    model: str = Field(default="", max_length=100)


@app.post("/api/query/outcome")
def query_outcome(body: Outcome, request: Request, user: identity.Identity = Depends(caller)):
    if body.outcome not in audit.OUTCOMES:
        raise HTTPException(400, f"outcome must be one of {', '.join(audit.OUTCOMES)}")
    question_id = audit.record_question(user=user.email, channel=channel(request), outcome=body.outcome,
                                        question=body.question, reason=body.reason, query_ids=body.query_ids,
                                        model=body.model, question_id=body.question_id)
    log.info("Question %s by %s: %s", question_id, user.email, body.outcome)
    return {"question_id": question_id, "outcome": body.outcome}

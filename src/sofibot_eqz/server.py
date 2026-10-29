"""Web portal: lists the built reports, serves them and rebuilds them on request or on a schedule.

Viewers: open, or HTTP Basic sign-in when SOFIBOT_VIEWER_PASSWORD is set.
Administration (/api/admin/...): Bearer SOFIBOT_ADMIN_TOKEN.
"""
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from html import escape
import logging
import mimetypes
import os
import secrets
import threading
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import __version__, config, projects
from .db import Gold

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sofibot")
build_lock = threading.Lock()
config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
# The slim image has no system MIME table: without this, Excel files are served as octet-stream.
mimetypes.add_type("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")


def build_reports(slugs: list[str], reason: str) -> dict:
    """Build one after another; a failure is logged and does not stop the others."""
    results = {}
    with build_lock:
        for slug in slugs:
            started = time.monotonic()
            try:
                projects.build(slug)
                results[slug] = "built"
                log.info("Built %s (%s) in %.1f s", slug, reason, time.monotonic() - started)
            except Exception:
                # Details stay in the server log: they can include values computed from real data.
                results[slug] = "failed"
                log.exception("Build failed: %s (%s)", slug, reason)
    return results


def schedule_times() -> list[tuple[int, int]]:
    times = []
    for value in os.environ.get("SOFIBOT_BUILD_SCHEDULE", "").split(","):
        if value.strip():
            hour, minute = value.strip().split(":")
            times.append((int(hour), int(minute)))
    return sorted(times)


def scheduler(times: list[tuple[int, int]]) -> None:
    while True:
        now = datetime.now()
        upcoming = [now.replace(hour=h, minute=m, second=0, microsecond=0) for h, m in times]
        upcoming = [moment if moment > now else moment + timedelta(days=1) for moment in upcoming]
        time.sleep((min(upcoming) - now).total_seconds())
        build_reports(list(projects.projects()), "schedule")


@asynccontextmanager
async def lifespan(_app):
    times = schedule_times()
    if times:
        threading.Thread(target=scheduler, args=(times,), daemon=True, name="build-schedule").start()
        log.info("Scheduled builds of every report at %s", ", ".join(f"{h:02d}:{m:02d}" for h, m in times))
    yield


app = FastAPI(title="Sofibot Equivalenza", version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def viewer_sign_in(request: Request, call_next):
    password = os.environ.get("SOFIBOT_VIEWER_PASSWORD", "")
    path = request.url.path
    if password and path != "/health" and not path.startswith("/api/admin/"):
        expected = f"{os.environ.get('SOFIBOT_VIEWER_USER', 'equivalenza')}:{password}".encode()
        supplied = request.headers.get("authorization", "")
        try:
            supplied = base64.b64decode(supplied[6:]) if supplied.startswith("Basic ") else b""
        except ValueError:
            supplied = b""
        if not secrets.compare_digest(supplied, expected):
            return JSONResponse({"detail": "Sign-in required"}, 401, {"WWW-Authenticate": 'Basic realm="Sofibot"'})
    return await call_next(request)


def require_admin(request: Request) -> None:
    token = os.environ.get("SOFIBOT_ADMIN_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "SOFIBOT_ADMIN_TOKEN is not configured (32 characters or more)")
    if not secrets.compare_digest(request.headers.get("authorization", "").encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "Administrator token required")


app.mount("/output", StaticFiles(directory=config.OUTPUT_DIR, html=True), name="output")


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/")
def root():
    return RedirectResponse("/dashboard")


@app.get("/api/reports")
def list_reports():
    return {"reports": projects.built(), "projects": list(projects.projects())}


@app.get("/api/admin/check", dependencies=[Depends(require_admin)])
async def database_check():
    try:
        return await run_in_threadpool(lambda: Gold().server_info())
    except Exception as exc:
        log.warning("Database check failed: %s", exc)
        raise HTTPException(503, "SQL Server unreachable or login rejected; see the server log")


@app.post("/api/admin/reports/{slug}/build", dependencies=[Depends(require_admin)])
async def build_one(slug: str):
    if slug not in projects.projects():
        raise HTTPException(404, "Unknown report project")
    if build_lock.locked():
        raise HTTPException(409, "Another build is running")
    result = await run_in_threadpool(build_reports, [slug], "api")
    if result[slug] != "built":
        raise HTTPException(500, "Build failed; see the server log")
    return {"slug": slug, "status": "built"}


@app.post("/api/admin/build-all", dependencies=[Depends(require_admin)])
async def build_all():
    if build_lock.locked():
        raise HTTPException(409, "Another build is running")
    return {"results": await run_in_threadpool(build_reports, list(projects.projects()), "api")}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    cards = []
    for report in projects.built():
        links = [f'<a class="primary" href="{escape(report["html"])}">Ver informe</a>'] if report["html"] else []
        links += [f'<a href="{escape(url)}" download>Excel · {escape(url.rsplit("/", 1)[-1])}</a>' for url in report["excel"]]
        built = datetime.fromtimestamp(report["built_at"]).strftime("%d/%m/%Y %H:%M")
        cards.append(f'<article><h2>{escape(report["name"])}</h2><p>{escape(report["description"])}</p>'
                     f'<p class="meta">Actualizado {built}</p><nav>{"".join(links)}</nav></article>')
    empty = "<p class='empty'>Todavía no hay informes generados. Ver <code>docs/04-crear-informes.md</code>.</p>"
    return DASHBOARD.replace("{cards}", "".join(cards) or empty)


DASHBOARD = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Informes · Sofibot</title><style>
:root{--blue:#2C3968;--orange:#D16B1B;--line:#dfe5ee}
*{box-sizing:border-box}body{margin:0;background:#f4f7fb;color:var(--blue);font:16px/1.5 Roboto,Arial,sans-serif}
header{background:var(--blue);color:#fff;padding:18px 24px}header h1{margin:0;font-size:22px;font-weight:500}
main{max-width:1100px;margin:auto;padding:24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
article{background:#fff;border:1px solid var(--line);border-top:4px solid var(--orange);border-radius:14px;padding:20px}
h2{margin:0 0 6px;font-size:19px}.meta{font-size:13px;color:#566173}.empty{grid-column:1/-1}
nav{display:flex;flex-wrap:wrap;gap:8px}a{color:var(--blue);font-weight:500;padding:7px 12px;border:1px solid var(--line);border-radius:8px;text-decoration:none}
a.primary{background:var(--blue);color:#fff}a:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
</style></head><body><header><h1>Sofibot · Informes</h1></header><main>{cards}</main></body></html>"""

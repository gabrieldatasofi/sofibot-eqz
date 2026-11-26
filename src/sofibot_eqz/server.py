"""Web portal: the pages for people (pages.py, review.py, admin.py), the built reports, the
report-code API of functionality 1 and the administration API; rebuilds reports on request or
on a schedule. Functionality 2 (queries) is a separate service: consultas/server.py.

Viewers (SOFIBOT_AUTH, auth.py): open, one shared HTTP Basic password, or each person with
Microsoft Entra ID, who then sees only the reports their roles allow (access.py).
Administration (/api/admin/...): Bearer SOFIBOT_ADMIN_TOKEN.
Report code (/api/code/...): the author's Entra ID token (SOFIBOT_CODE_API, drafts.api_mode).
Schema contract and report drafts for AI assistants (drafts.py): never data, and nothing it
writes is built until a reviewer publishes it.
"""
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import logging
import mimetypes
import os
import secrets
import threading
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, access, admin, auth, config, drafts, identity, pages, projects, review
from .db import Gold
from .identity import ROLE_AUTHOR, Identity

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sofibot")
build_lock = projects.BUILD_LOCK
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
    sign_in = auth.check_settings()
    log.info("Portal sign-in: %s", sign_in)
    if sign_in in auth.PER_USER:
        try:
            access.read()
        except access.PermissionsError as exc:
            log.warning("Permissions: %s. Signed-in users see no reports until it is fixed.", exc)
        try:
            accounts = access.read_local_accounts()
        except access.PermissionsError as exc:
            accounts = {}
            log.warning("Local accounts: %s. No local account can sign in until it is fixed.", exc)
        if accounts:
            log.info("Local accounts that can sign in without Entra ID: %s", ", ".join(sorted(accounts)))
        elif sign_in == "local":
            log.warning("SOFIBOT_AUTH=local but there is no local account: create one with  sofibot local-account add NAME")
    times = schedule_times()
    if times:
        threading.Thread(target=scheduler, args=(times,), daemon=True, name="build-schedule").start()
        log.info("Scheduled builds of every report at %s", ", ".join(f"{h:02d}:{m:02d}" for h, m in times))
    yield


app = FastAPI(title="Sofibot Equivalenza", version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def viewer_sign_in(request: Request, call_next):
    path = request.url.path
    if path == "/health" or path.startswith(("/api/admin/", "/api/code/")):  # these APIs have their own tokens
        return await call_next(request)
    if path in ("/", "/conexion.json") and auth.per_user():  # landing page; ids for the connector installer
        return await call_next(request)
    sign_in = auth.mode()
    if sign_in == "basic":
        expected = f"{os.environ.get('SOFIBOT_VIEWER_USER', 'equivalenza')}:{os.environ.get('SOFIBOT_VIEWER_PASSWORD', '')}"
        supplied = request.headers.get("authorization", "")
        try:
            supplied = base64.b64decode(supplied[6:]) if supplied.startswith("Basic ") else b""
        except ValueError:
            supplied = b""
        if not os.environ.get("SOFIBOT_VIEWER_PASSWORD") or not secrets.compare_digest(supplied, expected.encode()):
            return JSONResponse({"detail": "Sign-in required"}, 401, {"WWW-Authenticate": 'Basic realm="Sofibot"'})
    elif sign_in in auth.PER_USER and not path.startswith("/auth/") and not auth.session_valid(request):
        # No session, or one that no longer counts (local account removed or its password changed).
        request.session.pop("user", None)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Sign-in required"}, 401)
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/auth/login?next={quote(target)}", 302)
    return await call_next(request)


# Added after the middleware above so that it runs first and fills request.session.
# Signed (not encrypted) cookie: it holds the user's name, e-mail and roles, nothing secret.
# A new key on every start: after a restart users sign in again, silently with Entra ID.
app.add_middleware(
    SessionMiddleware, secret_key=secrets.token_urlsafe(48), session_cookie="sofibot_session",
    max_age=int(float(os.environ.get("SOFIBOT_SESSION_HOURS", "8")) * 3600), same_site="lax", https_only=True,
)
app.include_router(auth.router)


def require_admin(request: Request) -> None:
    token = os.environ.get("SOFIBOT_ADMIN_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "SOFIBOT_ADMIN_TOKEN is not configured (32 characters or more)")
    if not secrets.compare_digest(request.headers.get("authorization", "").encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "Administrator token required")


def code_caller(request: Request) -> Identity:
    """Who is calling the report-code API. It writes drafts; it never publishes or builds."""
    try:
        mode = drafts.api_mode()
    except drafts.DraftError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    header = request.headers.get("authorization", "")
    if mode == "off":
        raise HTTPException(503, "The report-code API is off (SOFIBOT_CODE_API)")
    if mode == "token":
        token = os.environ.get("SOFIBOT_API_TOKEN", "")
        if len(token) < 32 or token == os.environ.get("SOFIBOT_ADMIN_TOKEN"):
            raise HTTPException(503, "SOFIBOT_API_TOKEN is not configured (32 characters or more, different from the admin token)")
        if not secrets.compare_digest(header.encode(), f"Bearer {token}".encode()):
            raise HTTPException(401, "API token required")
        return Identity(email="token compartido", via="token")
    try:
        caller = identity.from_bearer(header)
    except identity.IdentityError as exc:
        raise HTTPException(401, str(exc)) from exc
    if ROLE_AUTHOR not in caller.roles:
        raise HTTPException(403, f"Your account does not have the {ROLE_AUTHOR} role")
    return caller


def draft_call(function, *arguments, action: str = "", **keywords):
    """Run a drafts.py function; refused requests become HTTP errors with a safe message."""
    try:
        result = function(*arguments, **keywords)
    except drafts.DraftError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    if action:
        log.info("Report code API: %s %s by %s", action, arguments[0] if arguments else keywords.get("slug", ""),
                 keywords.get("actor") or "?")
    return result


class NewDraft(BaseModel):
    slug: str
    name: str = ""
    table: str = ""
    description: str = ""
    from_report: bool = False


class FileContent(BaseModel):
    content: str


class Rejection(BaseModel):
    comment: str = ""


code = APIRouter(prefix="/api/code")


def caller_tables(caller: Identity) -> set[str] | None:
    return caller.tables(access.load())


@code.get("/schema")
def code_schema(caller: Identity = Depends(code_caller)):
    """Gold schema contract (the caller's tables) and report guide. Never opens the database."""
    return draft_call(drafts.describe_schema, caller_tables(caller))


@code.get("/reports")
def code_reports(caller: Identity = Depends(code_caller)):
    return {"reports": drafts.list_reports(caller_tables(caller))}


@code.get("/drafts")
def code_drafts(caller: Identity = Depends(code_caller)):
    return {"drafts": drafts.list_drafts(caller_tables(caller))}


@code.post("/drafts", status_code=201)
def code_create(body: NewDraft, caller: Identity = Depends(code_caller)):
    return draft_call(drafts.create_draft, body.slug, body.name, body.table, body.description,
                      from_report=body.from_report, actor=caller.email, tables=caller_tables(caller), action="create")


@code.get("/drafts/{slug}")
def code_status(slug: str, caller: Identity = Depends(code_caller)):
    return draft_call(drafts.draft_status, slug, caller_tables(caller))


@code.delete("/drafts/{slug}")
def code_delete(slug: str, caller: Identity = Depends(code_caller)):
    return draft_call(drafts.delete_draft, slug, actor=caller.email, tables=caller_tables(caller), action="delete")


@code.get("/drafts/{slug}/files/{name}")
def code_read(slug: str, name: str, caller: Identity = Depends(code_caller)):
    return draft_call(drafts.read_file, slug, name, caller_tables(caller))


@code.put("/drafts/{slug}/files/{name}")
def code_write(slug: str, name: str, body: FileContent, caller: Identity = Depends(code_caller)):
    return draft_call(drafts.write_file, slug, name, body.content, actor=caller.email, tables=caller_tables(caller),
                      action=f"write {name} in")


@code.post("/drafts/{slug}/check")
def code_check(slug: str, caller: Identity = Depends(code_caller)):
    return draft_call(drafts.check_draft, slug, caller_tables(caller))


@code.post("/drafts/{slug}/submit")
def code_submit(slug: str, caller: Identity = Depends(code_caller)):
    return draft_call(drafts.submit_draft, slug, actor=caller.email, tables=caller_tables(caller), action="submit")


app.include_router(code)
app.include_router(review.router)
app.include_router(pages.router)
app.include_router(admin.router)
ADMIN = "administrador (token)"


@app.get("/api/admin/drafts", dependencies=[Depends(require_admin)])
def admin_drafts():
    return {"drafts": drafts.list_drafts()}


@app.get("/api/admin/drafts/{slug}/files/{name}", dependencies=[Depends(require_admin)])
def admin_read(slug: str, name: str):
    return draft_call(drafts.read_file, slug, name)


@app.post("/api/admin/drafts/{slug}/publish", dependencies=[Depends(require_admin)])
def admin_publish(slug: str):
    """Copy a submitted draft into reports/. It is built at the next scheduled build or with the build API."""
    return draft_call(drafts.publish, slug, actor=ADMIN, action="publish")


@app.post("/api/admin/drafts/{slug}/reject", dependencies=[Depends(require_admin)])
def admin_reject(slug: str, body: Rejection):
    return draft_call(drafts.reject, slug, body.comment, actor=ADMIN, action="reject")


@app.api_route("/output/{slug}", methods=["GET", "HEAD"])
def report_folder(slug: str):
    return RedirectResponse(f"/output/{quote(slug)}/", 307)


@app.api_route("/output/{slug}/{file_path:path}", methods=["GET", "HEAD"])
def report_file(slug: str, file_path: str, request: Request):
    if not projects.SLUG.fullmatch(slug):
        raise HTTPException(404, "Not found")
    if not access.visible(auth.current_user(request), projects.built_tables(slug)):
        return auth.page("Sin acceso a este informe", "Tu usuario no tiene permiso para ver este informe. "
                         "Si lo necesitas, pide acceso a un administrador de Sofibot.", ("/informes", "Ir a mis informes"), status=403)
    folder = (config.OUTPUT_DIR / slug).resolve()
    target = (folder / file_path).resolve()
    if target.is_dir():
        target = target / "index.html"
    # resolve() + is_relative_to: '..' in the path cannot reach another report's folder.
    if not target.is_relative_to(folder) or not target.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(target, headers={"Cache-Control": "private, no-cache"})


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/reports")
def list_reports(request: Request):
    reports = pages.visible_reports(request)
    if auth.current_user(request) is not None:  # per-user sign-in: only what this user can see
        return {"reports": reports, "projects": [report["slug"] for report in reports]}
    return {"reports": reports, "projects": list(projects.projects())}


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

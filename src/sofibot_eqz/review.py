"""Functionality 1, review page: reviewers preview, publish or reject report drafts in the portal.

Only with Entra ID sign-in (SOFIBOT_AUTH=entra) and the Sofibot.Revisor role; a reviewer sees
only drafts whose Gold tables their roles allow. The preview runs the draft against the
database like `sofibot build`, into a folder only reviewers can open, and becomes the
published report when the reviewer publishes. Everything is recorded with the reviewer's
e-mail (drafts.py). Without Entra ID, `sofibot drafts|publish|reject` do the same on the server.
"""
from datetime import datetime
from html import escape
import logging
import os
import secrets
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from . import access, auth, drafts, projects, ui
from .identity import ROLE_REVIEWER, Identity, from_session

log = logging.getLogger("sofibot")
router = APIRouter(prefix="/revision")
STATUS = {"draft": "En edición", "submitted": "Enviado a revisión", "published": "Publicado", "rejected": "Rechazado"}


def reviewer(request: Request) -> tuple[Identity, set[str] | None]:
    if not auth.per_user():
        raise HTTPException(404, "Not found")
    user = from_session(auth.current_user(request) or {})
    if ROLE_REVIEWER not in user.roles:
        raise HTTPException(403, "Sofibot.Revisor role required")
    return user, user.tables(access.load())


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = request.session["csrf"] = secrets.token_urlsafe(32)
    return token


async def form(request: Request) -> dict[str, str]:
    """The posted form, after checking that it came from one of our pages (CSRF token)."""
    body = (await request.body()).decode("utf-8", "replace")
    fields = {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(fields.get("csrf", ""), expected):
        raise HTTPException(403, "The form expired: reload the page")
    return fields


def refused(exc: HTTPException) -> HTMLResponse:
    messages = {403: ("Sin permiso", "Tu usuario no tiene el rol de revisor de informes (Sofibot.Revisor)."),
                404: ("No encontrado", "La revisión de informes necesita el inicio de sesión con Entra ID.")}
    title, message = messages.get(exc.status_code, ("No se ha podido hacer", str(exc.detail)))
    if exc.status_code == 404 and "Draft" in str(exc.detail):
        title, message = "No encontrado", "Ese borrador no existe o no es de tus tablas."
    return auth.page(title, message, ("/revision", "Volver a la revisión"), status=exc.status_code)


@router.get("", response_class=HTMLResponse)
def index(request: Request):
    try:
        user, tables = reviewer(request)
    except HTTPException as exc:
        return refused(exc)
    rows = []
    found = sorted(drafts.list_drafts(tables), key=lambda d: (d["status"] != "submitted", d.get("updated_at", "")))
    for draft in found:
        rows.append(f'<tr><td><a href="/revision/{quote(draft["slug"], safe="")}">{escape(draft["name"] or draft["slug"])}</a></td>'
                    f'<td>{escape(STATUS.get(draft["status"], draft["status"]))}</td>'
                    f'<td>{escape(draft.get("submitted_by") or draft.get("created_by") or "")}</td>'
                    f'<td>{escape(when(draft.get("updated_at")))}</td></tr>')
    table = ("<table><tr><th>Informe</th><th>Estado</th><th>Autor</th><th>Último cambio</th></tr>"
             + "".join(rows) + "</table>") if rows else "<p>No hay borradores de informes sobre tus tablas.</p>"
    return ui.page(request, "Revisión de informes", f"<h1>Borradores de informes</h1>{table}", active="revision")


@router.get("/{slug}", response_class=HTMLResponse)
def detail(slug: str, request: Request, mensaje: str = ""):
    try:
        user, tables = reviewer(request)
        draft = drafts.draft_status(slug, tables)
    except HTTPException as exc:
        return refused(exc)
    except drafts.DraftError as exc:
        return refused(HTTPException(exc.status, str(exc)))
    token = csrf_token(request)
    status = draft["status"]
    parts = [f'<h1>{escape(draft["name"] or slug)}</h1><p class="meta">{escape(draft.get("description", ""))}</p>',
             f'<p><b>Estado:</b> {escape(STATUS.get(status, status))} · <b>Tablas:</b> '
             f'{escape(", ".join(draft.get("tables", [])))}</p>']
    if mensaje:
        parts.append(f'<p class="notice">{escape(mensaje)}</p>')
    if draft.get("comment"):
        parts.append(f'<p class="notice">Comentario del rechazo: {escape(draft["comment"])}</p>')
    if status == "submitted":
        hidden = f'<input type="hidden" name="csrf" value="{escape(token)}">'
        actions = [f'<form method="post" action="/revision/{quote(slug, safe="")}/vista-previa">{hidden}'
                   f'<button>{"Regenerar" if draft["has_preview"] else "Generar"} vista previa</button></form>']
        if draft["has_preview"]:
            actions.append(f'<a class="button" href="/revision/{quote(slug, safe="")}/vista-previa/" target="_blank">Abrir vista previa</a>')
        actions.append(f'<form method="post" action="/revision/{quote(slug, safe="")}/publicar">{hidden}'
                       f'<button class="primary">Publicar</button></form>')
        actions.append(f'<form method="post" action="/revision/{quote(slug, safe="")}/rechazar" class="reject">{hidden}'
                       '<input name="comment" maxlength="2000" placeholder="Qué hay que cambiar" required>'
                       '<button>Rechazar</button></form>')
        parts.append(f'<div class="actions">{"".join(actions)}</div>')
        parts.append('<p class="meta">La vista previa ejecuta el informe contra la base de datos, como un build, '
                     'y solo la ven los revisores. Al publicar, esa vista previa pasa a ser el informe del portal; '
                     'sin vista previa, se genera en el siguiente build programado.</p>')
    failure = drafts.preview_error(slug) if status == "submitted" else None
    if failure:
        parts.append('<h2>Error de la vista previa</h2><p class="meta">Solo lo ven los revisores: puede contener '
                     'valores reales. Para que el autor lo corrija, recházalo con un comentario que describa el error '
                     '(tipo y mensaje, por ejemplo la última línea) <b>sin copiar valores de datos</b>.</p>'
                     f"<pre>{escape(failure)}</pre>")
    for name in draft.get("files", []):
        try:
            code = drafts.read_file(slug, name, tables)["content"]
        except drafts.DraftError:
            continue
        parts.append(f"<h2>{escape(name)}</h2><pre>{escape(code)}</pre>")
    events = "".join(f'<li>{escape(when(e["at"]))} · {escape(e["who"])} · {escape(e["operation"])}'
                     f'{" · " + escape(e["detail"]) if e["detail"] else ""}</li>' for e in draft.get("history", []))
    parts.append(f"<h2>Historial</h2><ul>{events or '<li>Sin eventos</li>'}</ul>")
    return ui.page(request, f"{draft['name'] or slug} · Revisión", "".join(parts), active="revision")


async def act(slug: str, request: Request, action):
    try:
        user, tables = reviewer(request)
        fields = await form(request)
        message = await run_in_threadpool(action, user, tables, fields)
    except HTTPException as exc:
        return refused(exc)
    except drafts.DraftError as exc:
        message = str(exc)
    return RedirectResponse(f"/revision/{quote(slug, safe="")}?mensaje={quote(message)}", 303)


@router.post("/{slug}/vista-previa")
async def preview(slug: str, request: Request):
    def run(user, tables, _fields):
        if not projects.BUILD_LOCK.acquire(blocking=False):
            return "Hay otro build en marcha: vuelve a intentarlo en unos minutos."
        try:
            drafts.build_preview(slug, actor=user.email, tables=tables)
        finally:
            projects.BUILD_LOCK.release()
        log.info("Review: preview of %s by %s", slug, user.email)
        return "Vista previa generada."
    return await act(slug, request, run)


@router.post("/{slug}/publicar")
async def publish(slug: str, request: Request):
    def run(user, tables, _fields):
        result = drafts.publish(slug, actor=user.email, tables=tables,
                                own_review=os.environ.get("SOFIBOT_REVIEW_OWN") == "1")
        log.info("Review: %s published by %s", slug, user.email)
        return ("Publicado: ya está en el portal." if result["built"]
                else "Publicado: aparecerá en el portal tras el siguiente build.")
    return await act(slug, request, run)


@router.post("/{slug}/rechazar")
async def reject(slug: str, request: Request):
    def run(user, tables, fields):
        drafts.reject(slug, fields.get("comment", ""), actor=user.email, tables=tables)
        log.info("Review: %s rejected by %s", slug, user.email)
        return "Rechazado. El autor verá tu comentario."
    return await act(slug, request, run)


@router.api_route("/{slug}/vista-previa/{file_path:path}", methods=["GET", "HEAD"])
def preview_file(slug: str, file_path: str, request: Request):
    try:
        _user, tables = reviewer(request)
        drafts.draft_status(slug, tables)
    except HTTPException as exc:
        return refused(exc)
    except drafts.DraftError as exc:
        return refused(HTTPException(exc.status, str(exc)))
    folder = drafts.preview_dir(slug)
    if folder is None:
        raise HTTPException(404, "Not found")
    folder = folder.resolve()
    target = (folder / file_path).resolve()
    if target.is_dir():
        target = target / "index.html"
    if not target.is_relative_to(folder) or not target.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(target, headers={"Cache-Control": "private, no-store"})


def when(value: str | None) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d/%m/%Y %H:%M") if value else ""
    except ValueError:
        return value or ""

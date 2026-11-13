"""Administration page (role Sofibot.Admin, Entra ID sign-in only): how Sofibot is doing and how it works.

- /admin           status: SQL Server and the Gold schema contract, Entra ID, the two
                   functionalities and their MCP servers, permissions, versions
- /admin/permisos  edit reports/permisos.json (role -> Gold tables) from the browser
- /admin/docs      the technical documentation shipped with this version (docs/*.md)

Shows configuration and structure, never data and never secret values. Every change is
logged with the administrator's e-mail and the previous permissions file is kept.
"""
from contextlib import closing
from datetime import datetime, timezone
from html import escape
import json
import logging
import os
import platform
import re
import secrets
import sqlite3
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from . import __version__, access, auth, config, drafts, identity, pages, projects, ui
from .identity import ROLE_ADMIN, ROLE_AUTHOR, ROLE_QUERY, ROLE_REVIEWER

log = logging.getLogger("sofibot")
router = APIRouter(prefix="/admin")
ROLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
FUNCTION_ROLES = {ROLE_AUTHOR: "Escribir informes con un asistente de IA (funcionalidad 1)",
                  ROLE_REVIEWER: "Revisar, previsualizar y publicar borradores (funcionalidad 1)",
                  ROLE_QUERY: "Consultar datos (funcionalidad 2)",
                  ROLE_ADMIN: "Esta página de administración"}


def administrator(request: Request) -> identity.Identity:
    if auth.mode() != "entra":
        raise HTTPException(404, "La administración necesita el inicio de sesión con Entra ID (SOFIBOT_AUTH=entra).")
    who = ui.user(request)
    if who is None or ROLE_ADMIN not in who.roles:
        raise HTTPException(403, f"Tu usuario no tiene el rol de administración ({ROLE_ADMIN}).")
    return who


def refused(request: Request, exc: HTTPException) -> HTMLResponse:
    return ui.page(request, "Administración", f"<h1>Administración</h1>{ui.notice(str(exc.detail))}",
                   active="admin", status=exc.status_code)


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = request.session["csrf"] = secrets.token_urlsafe(32)
    return token


async def posted(request: Request) -> dict[str, list[str]]:
    fields = parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest((fields.get("csrf") or [""])[0], expected):
        raise HTTPException(403, "El formulario ha caducado: recarga la página.")
    return fields


def _registry() -> sqlite3.Connection:
    folder = config.REPORTS_DIR / ".admin"
    folder.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(folder / "registro.sqlite", timeout=10)
    connection.execute("CREATE TABLE IF NOT EXISTS eventos (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, "
                       "persona TEXT NOT NULL, operacion TEXT NOT NULL, detalle TEXT NOT NULL)")
    return connection


def record(who: str, operation: str, detail: str = "") -> None:
    with closing(_registry()) as connection, connection:
        connection.execute("INSERT INTO eventos (fecha, persona, operacion, detalle) VALUES (?, ?, ?, ?)",
                           (datetime.now(timezone.utc).isoformat(timespec="seconds"), who, operation, detail[:1000]))
    log.info("Admin: %s by %s (%s)", operation, who, detail[:200])


def recent_admin_events(limit: int = 10) -> list[tuple]:
    with closing(_registry()) as connection:
        return connection.execute("SELECT fecha, persona, operacion, detalle FROM eventos ORDER BY id DESC LIMIT ?",
                                  (limit,)).fetchall()


def state(ok: bool | None, text: str) -> str:
    css = {True: "ok", False: "bad", None: "warn"}[ok]
    return f'<span class="{css}">{escape(text)}</span>'


def masked(value: str) -> str:
    value = value.strip()
    return "—" if not value else (value[:8] + "…" if len(value) > 12 else value)


def contract() -> dict | None:
    try:
        return json.loads((config.REPORTS_DIR / config.SCHEMA_FILE.name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- Status -------------------------------------------------------------------------------

def database_section(check: bool) -> str:
    from .db import Settings

    settings, settings_error = None, ""
    try:
        settings = Settings.from_environment()
        rows = [("Servidor", settings.server), ("Base de datos", settings.database), ("Esquema Gold", settings.schema),
                ("Autenticación", settings.auth), ("Login", settings.user or "(Windows)"),
                ("Cifrado", f"{settings.encrypt}{' · certificado sin comprobar' if settings.trust_certificate else ''}"),
                ("Tiempo máximo por consulta", f"{settings.query_timeout} s")]
    except RuntimeError as exc:
        rows, settings_error = [], ui.notice(str(exc))
    result = ""
    if check and settings is not None:
        from .db import Gold, connection_hint

        try:
            info = Gold(settings).server_info()
            result = ("<table>" + "".join(f"<tr><th>{escape(k)}</th><td>{v}</td></tr>" for k, v in [
                ("Conexión", state(True, "Correcta")),
                ("Versión", escape(f"{info['version']} · {info['edition']}")),
                ("Login conectado", escape(info["login"])),
                ("El esquema existe", state(info["schema_exists"], "Sí" if info["schema_exists"] else "No")),
                ("Login de solo lectura", state(info["read_only_login"], "Sí" if info["read_only_login"]
                                                else "No: tiene permisos de escritura o es propietario")),
                ("Tablas y vistas que ve", str(len(info["tables"]))),
            ]) + "</table>")
        except Exception as exc:
            hint = connection_hint(exc)
            log.warning("Admin database check failed: %s", exc)
            result = ui.notice(f"No se puede conectar. {hint or 'Detalle en el log del portal.'}")
    schema = contract()
    if schema is None:
        schema_html = ui.notice("No existe reports/gold_schema.json: genéralo con el botón de abajo o con sofibot schema.")
    else:
        tables = schema.get("tables", {})
        documented = sum(1 for t in tables.values() if t.get("description"))
        schema_html = (f"<p>Contrato de esquema generado el {escape(str(schema.get('generated_at', '?')))}: "
                       f"{len(tables)} tablas y vistas ({documented} con descripción).</p>"
                       "<div class='scroll'><table><tr><th>Tabla</th><th>Tipo</th><th>Columnas</th><th>Descripción</th></tr>"
                       + "".join(f"<tr><td>{escape(n)}</td><td>{escape(t.get('type', ''))}</td>"
                                 f"<td class='num'>{len(t.get('columns', []))}</td><td>{escape(t.get('description', ''))}</td></tr>"
                                 for n, t in tables.items()) + "</table></div>")
    return f"""<h2 id="sql">SQL Server y tablas Gold</h2>
<p class="meta">Conexión del portal (builds de informes y vistas previas). El servicio de consultas tiene su propia
conexión y su propio login, en .env.consultas.</p>
{settings_error}<table>{"".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows)}</table>
<div class="actions"><a class="button" href="/admin?comprobar=1#sql">Comprobar la conexión</a>
<form method="post" action="/admin/esquema" style="margin:0"><input type="hidden" name="csrf" value="{{csrf}}">
<button>Actualizar el contrato de esquema</button></form></div>{result}
<h3>Contrato de esquema</h3>{schema_html}"""


def entra_section(who: identity.Identity) -> str:
    env = os.environ
    rows = [("Inicio de sesión del portal", state(auth.mode() == "entra", auth.mode())),
            ("Inquilino (tenant)", escape(masked(env.get("ENTRA_TENANT_ID", "")))),
            ("Aplicación (cliente)", escape(masked(env.get("ENTRA_CLIENT_ID", "")))),
            ("Secreto de cliente", state(bool(env.get("ENTRA_CLIENT_SECRET")), "Configurado" if env.get("ENTRA_CLIENT_SECRET") else "Falta")),
            ("Dirección pública", escape(env.get("SOFIBOT_PUBLIC_URL", "—"))),
            ("URI de redirección", escape(env.get("SOFIBOT_PUBLIC_URL", "").rstrip("/") + "/auth/callback")),
            ("Ámbito de la API (para consultas desde el portal)", escape(auth.api_scope() or "no se pide (sin SOFIBOT_QUERY_URL)")),
            ("Horas de sesión", escape(env.get("SOFIBOT_SESSION_HOURS", "8")))]
    try:
        keys = identity._jwks(identity.EntraApi.from_environment().tenant_id).get_signing_keys()
        rows.append(("Claves públicas de Entra ID", state(True, f"Accesibles ({len(keys)})")))
    except Exception:
        rows.append(("Claves públicas de Entra ID", state(False, "No accesibles: las APIs no podrán comprobar tokens")))
    mine = ", ".join(who.roles) or "(ninguno)"
    roles = "".join(f"<tr><td><code>{escape(r)}</code></td><td>{escape(d)}</td></tr>" for r, d in FUNCTION_ROLES.items())
    return f"""<h2 id="entra">Microsoft Entra ID</h2>
<table>{"".join(f"<tr><th>{escape(k)}</th><td>{v}</td></tr>" for k, v in rows)}</table>
<p class="meta">Tus roles: {escape(mine)}. Los roles se asignan en Entra ID (docs/09-inicio-sesion-entra.md).</p>
<h3>Roles de las funcionalidades</h3><table><tr><th>Rol</th><th>Para</th></tr>{roles}</table>"""


def functionality_one() -> str:
    try:
        mode = drafts.api_mode()
    except drafts.DraftError as exc:
        mode = str(exc)
    found = drafts.list_drafts()
    counts = {status: sum(1 for d in found if d["status"] == status) for status in pages.STATUS}
    events = "".join(f"<tr><td>{escape(e['at'][:16].replace('T', ' '))}</td><td>{escape(e['who'])}</td>"
                     f"<td>{escape(e['operation'])}</td><td>{escape(e['slug'])}</td></tr>" for e in drafts.events(10))
    return f"""<h2 id="informes">Funcionalidad 1 · crear informes</h2>
<table><tr><th>API de informes (/api/code)</th><td>{state(mode == "entra", mode)}</td></tr>
<tr><th>Informes publicados</th><td>{len(projects.projects())} proyectos, {len(projects.built())} generados</td></tr>
<tr><th>Borradores</th><td>{" · ".join(f"{pages.STATUS[k]}: {v}" for k, v in counts.items())}</td></tr>
<tr><th>Builds programados</th><td>{escape(os.environ.get("SOFIBOT_BUILD_SCHEDULE", "") or "ninguno")}</td></tr>
<tr><th>MCP</th><td><code>sofibot_informes_mcp.py</code>: describe_schema, list_reports, list_drafts, create_draft,
read_file, write_file, check_draft, submit_draft, draft_status, delete_draft. Nunca devuelve datos.</td></tr></table>
<h3>Últimas operaciones</h3>{f"<table><tr><th>Fecha (UTC)</th><th>Persona</th><th>Operación</th><th>Informe</th></tr>{events}</table>" if events else "<p>Ninguna.</p>"}"""


def functionality_two() -> str:
    from .consultas import catalog as catalog_module

    url = pages.query_url()
    if url:
        try:
            import requests

            response = requests.get(f"{url}/health", timeout=5)
            service = state(response.ok, "Responde" if response.ok else f"HTTP {response.status_code}")
        except Exception:
            service = state(False, "No responde")
    else:
        service = state(None, "No configurado (SOFIBOT_QUERY_URL)")
    try:
        entries = catalog_module.load()
        schema = contract()
        problems = catalog_module.problems_against(entries, schema) if schema else ["sin contrato de esquema"]
        catalog_html = state(not problems, f"{len(entries)} tablas" + (f"; problemas: {'; '.join(problems)}" if problems else ""))
        tables = "".join(f"<tr><td>{escape(t)}</td><td>{escape(', '.join(s['measures']))}</td>"
                         f"<td>{escape(', '.join(s['dimensions']))}</td></tr>" for t, s in entries.items())
    except catalog_module.CatalogError as exc:
        catalog_html, tables = state(False, str(exc)), ""
    detail = (f"<div class='scroll'><table><tr><th>Tabla</th><th>Medidas</th><th>Dimensiones</th></tr>{tables}</table></div>"
              if tables else "")
    return f"""<h2 id="consultas">Funcionalidad 2 · consultas de datos</h2>
<table><tr><th>Servicio de consultas</th><td>{service} <span class="meta">{escape(url)}</span></td></tr>
<tr><th>Catálogo (reports/catalogo.json)</th><td>{catalog_html}</td></tr>
<tr><th>MCP</th><td><code>sofibot_consultas_mcp.py</code>: describe_catalog, run_query, record_outcome. Devuelve
datos a la IA del usuario, con sus permisos.</td></tr>
<tr><th>Registro</th><td>En el contenedor de consultas: <code>consultas/registro.sqlite</code>
(<code>sofibot consultas-registro</code>). Nunca guarda valores.</td></tr></table>{detail}"""


@router.get("", response_class=HTMLResponse)
async def status_page(request: Request, comprobar: str = "", mensaje: str = ""):
    try:
        who = administrator(request)
    except HTTPException as exc:
        return refused(request, exc)
    sections = await run_in_threadpool(lambda: [
        database_section(comprobar == "1"), entra_section(who), functionality_one(), functionality_two()])
    events = "".join(f"<tr><td>{escape(at[:16].replace('T', ' '))}</td><td>{escape(p)}</td><td>{escape(o)}</td>"
                     f"<td>{escape(d)}</td></tr>" for at, p, o, d in recent_admin_events())
    body = f"""<h1>Administración</h1>{ui.notice(mensaje) if mensaje else ""}
<p class="meta">Sofibot {__version__} · Python {platform.python_version()} · inicio de sesión {auth.mode()}.
<a href="#sql">SQL Server</a> · <a href="#entra">Entra ID</a> · <a href="#informes">Informes</a> ·
<a href="#consultas">Consultas</a> · <a href="/conectar">MCP</a> · <a href="/admin/permisos">Permisos</a> ·
<a href="/admin/docs">Documentación</a></p>
<div class="cards"><article class="card"><h3>Permisos de usuarios</h3><p>Qué tablas Gold ve cada rol de Entra ID.</p>
<div class="actions"><a class="button primary" href="/admin/permisos">Editar permisos</a></div></article>
<article class="card"><h3>Conectores MCP</h3><p>Configuración para Claude y Codex de las dos funcionalidades.</p>
<div class="actions"><a class="button" href="/conectar">Ver configuración</a></div></article>
<article class="card"><h3>Documentación técnica</h3><p>Arquitectura, instalación, seguridad, Entra ID, APIs.</p>
<div class="actions"><a class="button" href="/admin/docs">Abrir</a></div></article></div>
{"".join(sections).replace("{csrf}", escape(csrf_token(request)))}
<h2>Cambios de administración</h2>{f"<table><tr><th>Fecha (UTC)</th><th>Persona</th><th>Operación</th><th>Detalle</th></tr>{events}</table>" if events else "<p>Ninguno.</p>"}"""
    return ui.page(request, "Administración", body, active="admin")


@router.post("/esquema")
async def refresh_schema(request: Request):
    """Rewrite reports/gold_schema.json from SQL Server's catalog: structure only, no rows."""
    try:
        who = administrator(request)
        await posted(request)
    except HTTPException as exc:
        return refused(request, exc)

    def write():
        from .schema import describe

        text = json.dumps(describe(), indent=2, ensure_ascii=False) + "\n"
        (config.REPORTS_DIR / config.SCHEMA_FILE.name).write_text(text, encoding="utf-8")

    try:
        await run_in_threadpool(write)
        record(who.email, "actualizar esquema")
        message = "Contrato de esquema actualizado."
    except Exception as exc:
        log.warning("Admin schema refresh failed: %s", exc)
        message = "No se ha podido actualizar: comprueba la conexión. Detalle en el log del portal."
    return RedirectResponse(f"/admin?mensaje={quote(message)}#sql", 303)


# --- Permissions --------------------------------------------------------------------------

def current_permissions() -> dict[str, list[str]]:
    try:
        data = json.loads(access.permissions_file().read_text(encoding="utf-8"))
        roles = data.get("roles", {}) if isinstance(data, dict) else {}
        return {r: list(t) for r, t in roles.items() if isinstance(t, list)}
    except (OSError, ValueError):
        return {}


@router.get("/permisos", response_class=HTMLResponse)
def permissions_page(request: Request, mensaje: str = ""):
    try:
        administrator(request)
    except HTTPException as exc:
        return refused(request, exc)
    roles = current_permissions()
    schema = contract() or {}
    tables = sorted({t.casefold() for t in schema.get("tables", {})} | {t for ts in roles.values() for t in ts if t != access.ALL})
    reports = {}
    for slug, path in projects.projects().items():
        try:
            reports[slug] = set(projects.manifest(path).get("tables") or [])
        except projects.ProjectError:
            continue
    head = "".join(f'<th title="{escape(t)}">{escape(t.split(".", 1)[-1])}</th>' for t in tables)
    rows = []
    for index, role in enumerate(sorted(roles) + [""]):
        granted = {t.casefold() for t in roles.get(role, [])}
        name = (f'<input type="hidden" name="role{index}" value="{escape(role)}"><b>{escape(role)}</b>'
                f'<br><label class="meta"><input type="checkbox" name="delete{index}" value="1"> quitar</label>') if role else \
            f'<input type="text" name="role{index}" placeholder="Nuevo rol (valor en Entra ID)">'
        cells = f'<td><input type="checkbox" name="tables{index}" value="*"{" checked" if access.ALL in granted else ""}></td>'
        cells += "".join(f'<td><input type="checkbox" name="tables{index}" value="{escape(t)}"'
                         f'{" checked" if t in granted else ""} aria-label="{escape(role)} {escape(t)}"></td>' for t in tables)
        seen = [slug for slug, ts in reports.items() if role and access.covers(granted, ts)]
        rows.append(f"<tr><td>{name}</td>{cells}<td class='meta'>{escape(', '.join(seen)) or '—'}</td></tr>")
    body = f"""<h1>Permisos de usuarios</h1>{ui.notice(mensaje) if mensaje else ""}
<p>Cada fila es un <b>rol de Entra ID</b> (su valor exacto) y las tablas Gold que puede tocar. Una persona con varios
roles suma sus tablas. Se aplica a todo: ver informes, crear informes (esquema visible) y consultar datos. Los cambios
se aplican al momento, sin reiniciar; el fichero anterior se guarda.</p>
<p class="meta">Los roles de funcionalidad ({", ".join(FUNCTION_ROLES)}) no van aquí: dan acceso a cada funcionalidad
y se asignan en Entra ID.</p>
<form method="post" action="/admin/permisos"><input type="hidden" name="csrf" value="{escape(csrf_token(request))}">
<div class="scroll"><table><tr><th>Rol</th><th>Todas (*)</th>{head}<th>Informes que ve</th></tr>{"".join(rows)}</table></div>
<input type="hidden" name="count" value="{len(roles) + 1}">
<div class="actions"><button class="primary">Guardar permisos</button>
<a class="button" href="/admin">Volver</a></div></form>"""
    return ui.page(request, "Permisos", body, active="admin")


@router.post("/permisos")
async def save_permissions(request: Request):
    try:
        who = administrator(request)
        fields = await posted(request)
    except HTTPException as exc:
        return refused(request, exc)
    schema = contract() or {}
    known = {t.casefold() for t in schema.get("tables", {})} | {access.ALL}
    roles, problems = {}, []
    for index in range(int((fields.get("count") or ["0"])[0] or 0)):
        role = (fields.get(f"role{index}") or [""])[0].strip()
        if not role or (fields.get(f"delete{index}") or [""])[0] == "1":
            continue
        if not ROLE_NAME.fullmatch(role):
            problems.append(f"Nombre de rol no válido: {role}")
            continue
        chosen = sorted(set(fields.get(f"tables{index}", [])))
        if unknown := [t for t in chosen if schema and t not in known]:
            problems.append(f"{role}: tablas desconocidas {', '.join(unknown)}")
            continue
        roles[role] = [access.ALL] if access.ALL in chosen else chosen
    if problems:
        return RedirectResponse(f"/admin/permisos?mensaje={quote('No se ha guardado. ' + '; '.join(problems))}", 303)
    path = access.permissions_file()
    previous = path.read_text(encoding="utf-8") if path.is_file() else None
    if previous is not None:
        backup = config.REPORTS_DIR / ".admin" / f"permisos-{datetime.now():%Y%m%d-%H%M%S}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(previous, encoding="utf-8")
    path.write_text(json.dumps({"roles": roles}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        access.read()
    except access.PermissionsError as exc:
        if previous is not None:
            path.write_text(previous, encoding="utf-8")
        return RedirectResponse(f"/admin/permisos?mensaje={quote(f'No se ha guardado: {exc}')}", 303)
    record(who.email, "permisos", json.dumps(roles, ensure_ascii=False))
    return RedirectResponse(f"/admin/permisos?mensaje={quote('Permisos guardados.')}", 303)


# --- Documentation ------------------------------------------------------------------------

DOC_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*\.md")


def doc_files() -> list:
    if not config.DOCS_DIR.is_dir():
        return []
    return sorted(path for path in config.DOCS_DIR.iterdir() if path.is_file() and DOC_NAME.fullmatch(path.name))


def doc_title(path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def render_markdown(text: str) -> str:
    import markdown
    from markdown.extensions.toc import TocExtension, slugify_unicode

    html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists",
                                               TocExtension(slugify=slugify_unicode)])
    # Links between documents stay inside the page; links to other repository files become plain text.
    html = re.sub(r'href="(?:\./)?([0-9A-Za-z][0-9A-Za-z._-]*)\.md(#[^"]*)?"', r'href="/admin/docs/\1.md\2"', html)
    return re.sub(r'<a href="(?!https?://|/admin/docs/|#)[^"]*">(.*?)</a>', r"\1", html)


@router.get("/docs", response_class=HTMLResponse)
def docs_index(request: Request):
    try:
        administrator(request)
    except HTTPException as exc:
        return refused(request, exc)
    items = "".join(f'<li><a href="/admin/docs/{quote(p.name)}">{escape(doc_title(p))}</a></li>' for p in doc_files())
    body = (f"<h1>Documentación técnica</h1><p class='meta'>La documentación de esta versión de Sofibot "
            f"({__version__}). Empieza por la arquitectura.</p><ul>{items or '<li>No se encuentra la carpeta docs/.</li>'}</ul>")
    return ui.page(request, "Documentación", body, active="admin")


@router.get("/docs/{name}", response_class=HTMLResponse)
def doc_page(name: str, request: Request):
    try:
        administrator(request)
    except HTTPException as exc:
        return refused(request, exc)
    path = config.DOCS_DIR / name
    if not DOC_NAME.fullmatch(name) or not path.is_file():
        return refused(request, HTTPException(404, "Documento no encontrado."))
    body = (f'<p class="meta"><a href="/admin/docs">Documentación</a></p>'
            f'<div class="doc">{render_markdown(path.read_text(encoding="utf-8"))}</div>')
    return ui.page(request, doc_title(path), body, active="admin")

"""Administration page (role Sofibot.Admin, Entra ID sign-in only): how Sofibot is doing and how it works.

- /admin           status: SQL Server and the Gold schema contract, Entra ID, the two
                   functionalities and their MCP servers, permissions, versions
- /admin/usuarios  edit acceso/usuarios.json (user -> roles): who may do what
- /admin/permisos  edit acceso/permisos.json (data role -> Gold tables)
- /admin/cuentas   local accounts; with SOFIBOT_LOCAL_ACCOUNTS_WEB=1, create TOTP accounts with a
                   temporary password (their owner sets a password and scans the QR code at the
                   first sign-in), reset or delete them. Password-only accounts: only on the
                   server, with  sofibot local-account
- /admin/docs      the technical documentation shipped with this version (docs/*.md)

Entra ID only signs users in; roles are given here (access.py). Shows configuration and
structure, never data and never secret values. Every change is logged with the
administrator's e-mail and the previous file is kept in acceso/.copias/.
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
ROLE_NAME = access.ROLE_NAME
FUNCTION_ROLES = {ROLE_AUTHOR: "Escribir informes con un asistente de IA (funcionalidad 1)",
                  ROLE_REVIEWER: "Revisar, previsualizar y publicar borradores (funcionalidad 1)",
                  ROLE_QUERY: "Consultar datos (funcionalidad 2)",
                  ROLE_ADMIN: "Esta página de administración"}


def administrator(request: Request) -> identity.Identity:
    if not auth.per_user():
        raise HTTPException(404, "La administración necesita inicio de sesión por persona (SOFIBOT_AUTH=entra o local).")
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
    if auth.mode() == "local":
        roles = "".join(f"<tr><td><code>{escape(r)}</code></td><td>{escape(d)}</td></tr>" for r, d in FUNCTION_ROLES.items())
        return f"""<h2 id="entra">Inicio de sesión</h2>
<p>{state(None, "Solo cuentas locales (SOFIBOT_AUTH=local)")}: sin Microsoft Entra ID. Tus roles: {escape(", ".join(who.roles) or "(ninguno)")}.</p>
{local_section()}<h3>Roles de las funcionalidades</h3><table><tr><th>Rol</th><th>Para</th></tr>{roles}</table>"""
    rows = [("Inicio de sesión del portal", state(auth.per_user(), auth.mode())),
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
{local_section()}
<p class="meta">Entra ID solo valida el inicio de sesión. Tus roles en Sofibot: {escape(mine)}. Los roles se
asignan en <a href="/admin/usuarios">Usuarios</a>.</p>
<h3>Roles de las funcionalidades</h3><table><tr><th>Rol</th><th>Para</th></tr>{roles}</table>"""


FULL_TAG = ' <span class="tag total">acceso total</span>'
OFF_TAG = ' <span class="tag">desactivada</span>'


def local_section() -> str:
    """Local accounts: who can sign in without Entra ID. Never shows a hash or a secret."""
    try:
        enabled, problem = access.enabled_kinds(), ""
    except access.PermissionsError as exc:
        enabled, problem = (), str(exc)
    rows = []
    for kind, label in ((access.PASSWORD, "Cuentas locales (usuario y contraseña)"),
                        (access.TOTP, "Cuentas locales con TOTP (contraseña y código de la app)")):
        try:
            names = ", ".join(f"{n} (acceso total)" if identity.full_access(a["roles"]) else n
                              for n, a in sorted(access.read_accounts(kind).items())) or "ninguna"
            value = (state(True if names == "ninguna" else None, names) if kind in enabled
                     else state(None, f"Desactivadas en SOFIBOT_LOCAL_ACCOUNTS ({names})"))
        except access.PermissionsError as exc:
            value = state(False, str(exc))
        rows.append((label, value))
    if problem:
        rows.append(("SOFIBOT_LOCAL_ACCOUNTS", state(False, problem)))
    rows.append(("Tokens para sus conectores (SOFIBOT_LOCAL_SECRET)",
                 state(True, f"Configurado · duran {identity.token_days()} días") if identity.local_secret()
                 else state(None, "No configurado: las cuentas locales no pueden usar conectores ni Consultas")))
    return f"""<h3 id="locales">Cuentas locales (sin Entra ID)</h3>
<table>{"".join(f"<tr><th>{escape(k)}</th><td>{v}</td></tr>" for k, v in rows)}</table>
<p class="meta">Entran sin pasar por Microsoft: sirven de acceso de emergencia. Las cuentas con TOTP piden además el
código de una aplicación de autenticación. Se gestionan en el servidor con <code>sofibot local-account</code>
(docs/09-inicio-sesion-entra.md). Cada entrada queda en el registro del portal; tras 5 intentos erróneos en
15 minutos el acceso se bloquea un rato.</p>"""


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
<table><tr><th>API de informes (/api/code)</th><td>{state(mode in drafts.PER_USER_MODES, mode)}</td></tr>
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
<a href="#consultas">Consultas</a> · <a href="/conectar">MCP</a> · <a href="/admin/usuarios">Usuarios</a> ·
<a href="/admin/permisos">Permisos</a> · <a href="/admin/cuentas">Cuentas locales</a> ·
<a href="/admin/docs">Documentación</a></p>
<div class="cards"><article class="card"><h3>Usuarios</h3><p>Quién entra en Sofibot y con qué roles.</p>
<div class="actions"><a class="button primary" href="/admin/usuarios">Editar usuarios</a></div></article>
<article class="card"><h3>Permisos por tabla</h3><p>Qué tablas Gold da cada rol de datos.</p>
<div class="actions"><a class="button" href="/admin/permisos">Editar permisos</a></div></article>
<article class="card"><h3>Cuentas locales</h3><p>Cuentas sin Entra ID, con contraseña y código TOTP del móvil.</p>
<div class="actions"><a class="button" href="/admin/cuentas">Ver cuentas</a></div></article>
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
            f'<input type="text" name="role{index}" placeholder="Nuevo rol de datos">'
        cells = f'<td><input type="checkbox" name="tables{index}" value="*"{" checked" if access.ALL in granted else ""}></td>'
        cells += "".join(f'<td><input type="checkbox" name="tables{index}" value="{escape(t)}"'
                         f'{" checked" if t in granted else ""} aria-label="{escape(role)} {escape(t)}"></td>' for t in tables)
        seen = [slug for slug, ts in reports.items() if role and access.covers(granted, ts)]
        rows.append(f"<tr><td>{name}</td>{cells}<td class='meta'>{escape(', '.join(seen)) or '—'}</td></tr>")
    legacy = access.permissions_file() == access.legacy_permissions_file()
    body = f"""<h1>Permisos por tabla</h1>{ui.notice(mensaje) if mensaje else ""}
<p>Cada fila es un <b>rol de datos</b> y las tablas Gold que puede tocar. Los roles se dan a cada persona en
<a href="/admin/usuarios">Usuarios</a>; una persona con varios roles suma sus tablas. Se aplica a todo: ver informes,
crear informes (esquema visible) y consultar datos. Los cambios se aplican al momento, sin reiniciar; el fichero
anterior se guarda.</p>
<p class="meta">Los roles de funcionalidad ({", ".join(FUNCTION_ROLES)}) no van aquí: dan acceso a cada
funcionalidad, no a tablas.</p>
{ui.notice("Estos permisos están todavía en reports/permisos.json (instalación anterior). Al guardar pasan a "
           "acceso/permisos.json, que es el que se usará desde entonces.") if legacy else ""}
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
        if role in FUNCTION_ROLES:
            problems.append(f"{role} es un rol de funcionalidad: no lleva tablas")
            continue
        chosen = sorted(set(fields.get(f"tables{index}", [])))
        if unknown := [t for t in chosen if schema and t not in known]:
            problems.append(f"{role}: tablas desconocidas {', '.join(unknown)}")
            continue
        roles[role] = [access.ALL] if access.ALL in chosen else chosen
    if problems:
        return RedirectResponse(f"/admin/permisos?mensaje={quote('No se ha guardado. ' + '; '.join(problems))}", 303)
    try:
        access.save_permissions(roles)
    except (OSError, access.PermissionsError) as exc:
        return RedirectResponse(f"/admin/permisos?mensaje={quote(f'No se ha guardado: {exc}')}", 303)
    record(who.email, "permisos", json.dumps(roles, ensure_ascii=False))
    return RedirectResponse(f"/admin/permisos?mensaje={quote('Permisos guardados.')}", 303)


# --- Users --------------------------------------------------------------------------------

def current_users() -> tuple[dict[str, tuple[str, ...]], str]:
    """Users and roles, plus a problem to show if the file is broken (then the page starts empty)."""
    if not access.users_file().is_file():
        return {}, ""
    try:
        return access.read_users(), ""
    except access.PermissionsError as exc:
        return {}, f"El fichero de usuarios no es válido y nadie tiene roles hasta corregirlo: {exc}"


@router.get("/usuarios", response_class=HTMLResponse)
def users_page(request: Request, mensaje: str = ""):
    try:
        administrator(request)
    except HTTPException as exc:
        return refused(request, exc)
    users, problem = current_users()
    permissions = access.load()
    data_roles = sorted(set(permissions) | {r for rs in users.values() for r in rs if r not in FUNCTION_ROLES})
    columns = list(FUNCTION_ROLES) + data_roles
    head = "".join(f'<th title="{escape(FUNCTION_ROLES.get(r, "Rol de datos"))}">'
                   f'{escape(r.removeprefix("Sofibot."))}</th>' for r in columns)
    rows = []
    for index, email in enumerate(sorted(users) + [""]):
        mine = set(users.get(email, ()))
        if email:
            name = (f'<input type="hidden" name="email{index}" value="{escape(email)}"><b>{escape(email)}</b>'
                    f'<br><label class="meta"><input type="checkbox" name="delete{index}" value="1"> quitar</label>')
        else:
            name = f'<input type="email" name="email{index}" placeholder="correo de Microsoft de la persona">'
        cells = "".join(f'<td><input type="checkbox" name="roles{index}" value="{escape(r)}"'
                        f'{" checked" if r in mine else ""} aria-label="{escape(email)} {escape(r)}"></td>' for r in columns)
        tables = access.granted(mine, permissions)
        summary = "todas" if access.ALL in tables else ", ".join(sorted(t.split(".", 1)[-1] for t in tables))
        if unknown := sorted(r for r in mine if r not in FUNCTION_ROLES and r not in permissions):
            summary += f" (sin tablas en Permisos: {', '.join(unknown)})"
        rows.append(f"<tr><td>{name}</td>{cells}<td class='meta'>{escape(summary) or '—'}</td></tr>")
    functions = "; ".join(f"<code>{escape(r)}</code>: {escape(d)}" for r, d in FUNCTION_ROLES.items())
    accounts = access.load_local_accounts()
    local_rows = "".join(f"<tr><td><b>{escape(name)}</b> <span class='tag'>cuenta local{' · TOTP' if a['tipo'] == access.TOTP else ''}</span>"
                         f"{FULL_TAG if identity.full_access(a['roles']) else ''}</td>"
                         f"<td>{escape(', '.join('todas las tablas' if r == access.ALL else r for r in a['roles']))}</td></tr>"
                         for name, a in sorted(accounts.items()))
    local_html = (f"""<h2>Cuentas locales</h2><p class="meta">Entran con usuario y contraseña (y un código TOTP si lo tienen), sin Microsoft. Sus roles van
con la cuenta y se gestionan en <a href="/admin/cuentas">Cuentas locales</a> o en el servidor con <code>sofibot local-account</code>.</p>
<table><tr><th>Usuario</th><th>Roles</th></tr>{local_rows}</table>
<p class="meta"><span class="tag total">acceso total</span> todos los roles y todas las tablas Gold, sean cuales sean,
sin depender de Permisos por tabla (docs/09-inicio-sesion-entra.md, cuentas de acceso total).</p>""" if accounts else "")
    body = f"""<h1>Usuarios</h1>{ui.notice(mensaje) if mensaje else ""}{ui.notice(problem) if problem else ""}
<p>Microsoft Entra ID solo valida el inicio de sesión: dice quién es cada persona. Lo que puede hacer en Sofibot
se decide aquí. Cada fila es una persona, por su <b>correo de Microsoft</b> (con el que inicia sesión), y sus roles:</p>
<ul><li><b>Roles de funcionalidad</b>, qué puede hacer. {functions}.</li>
<li><b>Roles de datos</b>, qué tablas Gold ve: se definen en <a href="/admin/permisos">Permisos por tabla</a>.</li></ul>
<p class="meta">Quien no está en esta lista puede iniciar sesión pero no ve nada. Los cambios se aplican al momento,
sin volver a iniciar sesión; el fichero anterior se guarda.</p>
<form method="post" action="/admin/usuarios"><input type="hidden" name="csrf" value="{escape(csrf_token(request))}">
<div class="scroll"><table><tr><th>Usuario</th>{head}<th>Tablas que ve</th></tr>{"".join(rows)}</table></div>
<input type="hidden" name="count" value="{len(users) + 1}">
<div class="actions"><button class="primary">Guardar usuarios</button>
<a class="button" href="/admin">Volver</a></div></form>{local_html}"""
    return ui.page(request, "Usuarios", body, active="admin")


@router.post("/usuarios")
async def save_users(request: Request):
    try:
        who = administrator(request)
        fields = await posted(request)
    except HTTPException as exc:
        return refused(request, exc)
    users, problems = {}, []
    for index in range(int((fields.get("count") or ["0"])[0] or 0)):
        email = (fields.get(f"email{index}") or [""])[0].strip().casefold()
        if not email or (fields.get(f"delete{index}") or [""])[0] == "1":
            continue
        if not access.EMAIL.fullmatch(email):
            problems.append(f"Correo no válido: {email}")
            continue
        roles = sorted(set(fields.get(f"roles{index}", [])))
        if bad := [r for r in roles if not ROLE_NAME.fullmatch(r)]:
            problems.append(f"{email}: roles no válidos {', '.join(bad)}")
            continue
        users[email] = roles
    if who.via == "entra" and ROLE_ADMIN not in users.get(who.email.casefold(), []):
        problems.append(f"No puedes quitarte a ti mismo el rol {ROLE_ADMIN}: que lo haga otro administrador")
    if problems:
        return RedirectResponse(f"/admin/usuarios?mensaje={quote('No se ha guardado. ' + '; '.join(problems))}", 303)
    try:
        access.save_users(users)
    except (OSError, access.PermissionsError) as exc:
        return RedirectResponse(f"/admin/usuarios?mensaje={quote(f'No se ha guardado: {exc}')}", 303)
    record(who.email, "usuarios", json.dumps(users, ensure_ascii=False))
    return RedirectResponse(f"/admin/usuarios?mensaje={quote('Usuarios guardados.')}", 303)


# --- Local accounts with TOTP, from the portal (SOFIBOT_LOCAL_ACCOUNTS_WEB=1) ------------
# The administrator gives a temporary password; at the first sign-in its owner chooses their own
# password and scans their QR code (auth.py, /auth/activar): the administrator never sees it.

def accounts_web(env=os.environ) -> bool:
    """SOFIBOT_LOCAL_ACCOUNTS_WEB=1: administrators may create TOTP accounts from the portal."""
    return env.get("SOFIBOT_LOCAL_ACCOUNTS_WEB", "").strip().lower() in ("1", "true", "yes", "si", "sí")


def all_local_accounts() -> tuple[dict[str, dict], list[str]]:
    """Every local account of both files, enabled or not, and the problems reading them."""
    accounts, problems = {}, []
    for kind in access.KINDS:
        try:
            accounts.update(access.read_accounts(kind))
        except access.PermissionsError as exc:
            problems.append(str(exc))
    return accounts, problems


def back_to_accounts(message: str) -> RedirectResponse:
    return RedirectResponse(f"/admin/cuentas?mensaje={quote(message)}", 303)


def local_date(value: datetime) -> str:
    return value.astimezone().strftime("%d/%m/%Y %H:%M")


def account_state(account: dict) -> str:
    if account["tipo"] != access.TOTP:
        return ""
    if not access.pending(account):
        return " <span class='tag'>activada</span>"
    if access.expired(account):
        return " <span class='tag'>contraseña temporal caducada: restablécela</span>"
    return f" <span class='tag'>pendiente de activar hasta {escape(local_date(account['activar_hasta']))}</span>"


@router.get("/cuentas", response_class=HTMLResponse)
def accounts_page(request: Request, mensaje: str = ""):
    try:
        who = administrator(request)
    except HTTPException as exc:
        return refused(request, exc)
    web = accounts_web()
    accounts, problems = all_local_accounts()
    try:
        enabled = access.enabled_kinds()
    except access.PermissionsError as exc:
        enabled, problems = (), [*problems, str(exc)]
    token = escape(csrf_token(request))
    rows = []
    for name, a in sorted(accounts.items()):
        roles = ", ".join("todas las tablas" if r == access.ALL else r for r in a["roles"]) or "(ninguno)"
        tags = (f"<span class='tag'>{'TOTP' if a['tipo'] == access.TOTP else 'solo contraseña'}</span>"
                f"{FULL_TAG if identity.full_access(a['roles']) else ''}{account_state(a)}"
                f"{'' if a['tipo'] in enabled else OFF_TAG}")
        actions = "<span class='meta'>en el servidor</span>"
        if web and a["tipo"] == access.TOTP:
            if who.via == "local" and who.email == name:
                actions = "<span class='meta'>tu cuenta</span>"
            else:
                hidden = f'<input type="hidden" name="csrf" value="{token}"><input type="hidden" name="usuario" value="{escape(name)}">'
                actions = (f'<form method="post" action="/admin/cuentas/restablecer" class="inline">{hidden}'
                           f'<button title="Nueva contraseña temporal: la persona vuelve a elegir contraseña y a escanear el QR">'
                           f'Restablecer</button></form> <form method="post" action="/admin/cuentas/borrar" class="inline">{hidden}'
                           f'<label class="meta"><input type="checkbox" name="confirmo" value="1" required> confirmo</label> '
                           f'<button>Borrar</button></form>')
        rows.append(f"<tr><td><b>{escape(name)}</b> {tags}<br><span class='meta'>{escape(a['nombre'])}</span></td>"
                    f"<td>{escape(roles)}</td><td>{actions}</td></tr>")
    table = (f"<table><tr><th>Usuario</th><th>Roles</th><th>Acciones</th></tr>{''.join(rows)}</table>"
             if rows else "<p>No hay cuentas locales.</p>")
    if web:
        data_roles = sorted(access.load())
        checks = "".join(f'<label class="check"><input type="checkbox" name="roles" value="{escape(r)}"> {escape(r)}</label>'
                         for r in [*FUNCTION_ROLES, *data_roles])
        create = f"""<h2>Nueva cuenta con TOTP</h2>
<p>Sofibot genera una <b>contraseña temporal</b>, que verás una sola vez: dásela a la persona por un canal aparte.
La primera vez que entre, elegirá su propia contraseña y escaneará su código QR con una aplicación de autenticación
del móvil; desde entonces entrará con su contraseña y el código de 6 dígitos. Si no la activa en
{access.activation_days()} días, la contraseña temporal caduca y hay que restablecerla.</p>
<form method="post" action="/admin/cuentas/nueva" class="stack"><input type="hidden" name="csrf" value="{token}">
<label>Usuario <span class="meta">(minúsculas, números, punto, guion; sin @)</span>
<input name="usuario" required pattern="[a-z0-9][a-z0-9._-]{{1,63}}" maxlength="64"></label>
<label>Nombre visible <input name="nombre" maxlength="80"></label>
<fieldset><legend>Acceso</legend>
<label><input type="radio" name="acceso" value="total" checked> <b>Acceso total</b>: todos los roles y todas las
tablas Gold, sean cuales sean</label>
<label><input type="radio" name="acceso" value="roles"> Solo estos roles:</label><div class="checks">{checks}</div>
</fieldset>
<div class="actions"><button class="primary">Crear cuenta</button></div></form>"""
        if access.TOTP not in enabled:
            create = ui.notice("Las cuentas con TOTP están desactivadas en SOFIBOT_LOCAL_ACCOUNTS: las que crees no "
                               "podrán entrar hasta que se activen.") + create
    else:
        create = """<p class="meta">Crear cuentas desde el portal está desactivado. Se gestionan en el servidor con
<code>sofibot local-account</code>; para crear cuentas con TOTP desde aquí, <code>SOFIBOT_LOCAL_ACCOUNTS_WEB=1</code>
en <code>.env</code> (docs/09-inicio-sesion-entra.md).</p>"""
    body = f"""<h1>Cuentas locales</h1>{ui.notice(mensaje) if mensaje else ""}{"".join(ui.notice(p) for p in problems)}
<p>Entran en Sofibot sin Microsoft Entra ID, con sus propios roles. Las cuentas con TOTP piden además el código de
una aplicación del móvil. Las de solo contraseña se gestionan únicamente en el servidor
(<code>sofibot local-account</code>). Tipos que pueden entrar ahora (SOFIBOT_LOCAL_ACCOUNTS):
{escape(", ".join(enabled) or "ninguno")}.</p>
{table}
<p class="meta"><span class="tag total">acceso total</span> todos los roles y todas las tablas Gold, sean cuales sean,
sin depender de Permisos por tabla.</p>
{create}
<div class="actions"><a class="button" href="/admin">Volver</a></div>"""
    return ui.page(request, "Cuentas locales", body, active="admin")


def web_administrator(request: Request) -> identity.Identity:
    who = administrator(request)
    if not accounts_web():
        raise HTTPException(404, "Crear cuentas desde el portal está desactivado (SOFIBOT_LOCAL_ACCOUNTS_WEB).")
    return who


def temporary_password_page(request: Request, title: str, name: str, password: str, until: datetime) -> HTMLResponse:
    """The temporary password, shown once: the response is not kept by the browser."""
    body = f"""<h1>{escape(title)}: {escape(name)}</h1>
<p>Contraseña temporal. Se muestra <b>solo ahora</b>: cópiala y dásela a la persona por un canal distinto del
nombre de usuario (por ejemplo, el usuario por correo y la contraseña por teléfono o en el gestor de contraseñas).</p>
<p><code class="once">{escape(password)}</code></p>
<p>Vale hasta el <b>{escape(local_date(until))}</b>. La primera vez que entre con ella, Sofibot le pedirá elegir su
propia contraseña y escanear su código QR con una aplicación de autenticación del móvil. Ni tú ni nadie más verá
ese QR.</p>
<div class="actions"><a class="button primary" href="/admin/cuentas">Hecho</a></div>"""
    response = ui.page(request, "Cuentas locales", body, active="admin")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/cuentas/nueva")
async def new_account(request: Request):
    try:
        who = web_administrator(request)
        fields = await posted(request)
    except HTTPException as exc:
        return refused(request, exc)
    field = lambda name: (fields.get(name) or [""])[0].strip()  # noqa: E731
    name = field("usuario").casefold()
    if not access.USERNAME.fullmatch(name):
        return back_to_accounts("No se ha creado: el usuario lleva minúsculas, números, '.', '_' o '-', sin '@'.")
    accounts, problems = all_local_accounts()
    if problems:
        return back_to_accounts("No se ha creado: " + "; ".join(problems))
    if name in accounts:
        return back_to_accounts(f"No se ha creado: ya existe la cuenta {name}.")
    if field("acceso") == "total":
        roles = [*FUNCTION_ROLES, access.ALL]
    else:
        roles = sorted(set(fields.get("roles", [])))
        if not roles or any(not ROLE_NAME.fullmatch(r) for r in roles):
            return back_to_accounts("No se ha creado: elige acceso total o al menos un rol válido.")
    password = secrets.token_urlsafe(18)
    until = access.activation_deadline()
    totp_accounts = {n: dict(a) for n, a in access.read_totp_accounts().items()}
    totp_accounts[name] = {"nombre": field("nombre")[:80] or name, "version": 1, "roles": roles, "totp": None,
                           "activar_hasta": until,
                           "hash": await run_in_threadpool(identity.hash_password, password)}
    try:
        access.save_totp_accounts(totp_accounts)
    except (OSError, access.PermissionsError) as exc:
        return back_to_accounts(f"No se ha creado: {exc}")
    record(who.email, "cuenta local TOTP nueva", f"{name}: {', '.join(roles)}; pendiente de activar")
    return temporary_password_page(request, "Cuenta creada", name, password, until)


@router.post("/cuentas/restablecer")
async def reset_account(request: Request):
    try:
        who = web_administrator(request)
        fields = await posted(request)
    except HTTPException as exc:
        return refused(request, exc)
    name = (fields.get("usuario") or [""])[0].strip().casefold()
    if who.via == "local" and who.email == name:
        return back_to_accounts("No puedes restablecer la cuenta con la que has entrado.")
    try:
        accounts = {n: dict(a) for n, a in access.read_totp_accounts().items()}
    except access.PermissionsError as exc:
        return back_to_accounts(f"No se ha restablecido: {exc}")
    if name not in accounts:
        return back_to_accounts(f"{name} no es una cuenta con TOTP (las demás, en el servidor).")
    password, until = secrets.token_urlsafe(18), access.activation_deadline()
    accounts[name].update(hash=await run_in_threadpool(identity.hash_password, password), totp=None,
                          activar_hasta=until, version=accounts[name]["version"] + 1)
    try:
        access.save_totp_accounts(accounts)
    except (OSError, access.PermissionsError) as exc:
        return back_to_accounts(f"No se ha restablecido: {exc}")
    record(who.email, "cuenta local TOTP restablecida", name)
    return temporary_password_page(request, "Cuenta restablecida", name, password, until)


@router.post("/cuentas/borrar")
async def delete_account(request: Request):
    try:
        who = web_administrator(request)
        fields = await posted(request)
    except HTTPException as exc:
        return refused(request, exc)
    name = (fields.get("usuario") or [""])[0].strip().casefold()
    if (fields.get("confirmo") or [""])[0] != "1":
        return back_to_accounts("No se ha borrado: marca «confirmo».")
    if who.via == "local" and who.email == name:
        return back_to_accounts("No puedes borrar la cuenta con la que has entrado.")
    try:
        accounts = {n: dict(a) for n, a in access.read_totp_accounts().items()}
        if name not in accounts:
            return back_to_accounts(f"{name} no es una cuenta con TOTP (las demás, en el servidor).")
        del accounts[name]
        access.save_totp_accounts(accounts)
    except (OSError, access.PermissionsError) as exc:
        return back_to_accounts(f"No se ha borrado: {exc}")
    record(who.email, "cuenta local TOTP borrada", name)
    return back_to_accounts(f"Cuenta {name} borrada: sus sesiones y tokens ya no valen.")


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

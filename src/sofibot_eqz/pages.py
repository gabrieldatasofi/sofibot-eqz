"""Portal pages for people: landing, Explore Sofibot, reports, queries and "connect your AI".

- /            landing: sign in with Microsoft (Entra ID); without Entra ID, straight to /explore
- /explore     the two functionalities, as the user's roles allow
- /informes    functionality 1: published reports the user may see (theirs marked) and their drafts
- /consultas   functionality 2: a query form. The portal does not query the database: it forwards
               the user's request, with the user's own token, to the query service (consultas/)
- /conectar    how to connect Claude or Codex to the two MCP servers, with a download
"""
from datetime import datetime
from html import escape
import io
import json
import os
import re
import zipfile

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from . import access, auth, config, drafts, projects, ui
from .formatting import display_value
from .identity import ROLE_AUTHOR, ROLE_QUERY, ROLE_REVIEWER

router = APIRouter()
MCP_FILES = ["LEEME.md", "requirements.txt", "sofibot_entra.py", "sofibot_informes_mcp.py", "sofibot_consultas_mcp.py",
             "codigo_del_programa.py", "sofibot_instalar.py", "build-exe.ps1"]
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(T.*)?")
STATUS = {"draft": "En edición", "submitted": "Enviado a revisión", "published": "Publicado", "rejected": "Rechazado"}


def query_url() -> str:
    return os.environ.get("SOFIBOT_QUERY_URL", "").strip().rstrip("/")


# --- Landing and Explore ------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    if auth.mode() != "entra" or request.session.get("user"):
        return RedirectResponse("/explore", 302)
    return HTMLResponse(LANDING)


@router.get("/explore", response_class=HTMLResponse)
def explore(request: Request):
    who = ui.user(request)
    entra = who is not None
    reports = visible_reports(request)
    roles = set(who.roles) if entra else set()
    author, querier = (not entra) or ROLE_AUTHOR in roles, entra and ROLE_QUERY in roles
    report_actions = [f'<a class="button primary" href="/informes">Ver informes ({len(reports)})</a>']
    if author and drafts.api_mode() != "off":
        report_actions.append('<a class="button" href="/informes#crear">Crear con tu IA</a>')
    if entra and ROLE_REVIEWER in roles:
        pending = sum(1 for d in drafts.list_drafts(who.tables(access.load())) if d["status"] == "submitted")
        report_actions.append(f'<a class="button" href="/revision">Revisar ({pending})</a>')
    if querier and query_url():
        query_card = ('<p>Pregunta a los datos de tus tablas Gold: medidas por dimensiones y periodo, al momento. '
                      'Desde el portal o desde Claude o Codex.</p><div class="actions">'
                      '<a class="button primary" href="/consultas">Consultar</a>'
                      '<a class="button" href="/conectar#consultas">Conectar tu IA</a></div>')
    elif not query_url():
        query_card = '<p class="meta">El servicio de consultas no está activado en esta instalación.</p>'
    elif not entra:
        query_card = '<p class="meta">Las consultas necesitan el inicio de sesión con Microsoft Entra ID.</p>'
    else:
        query_card = '<p class="meta">Tu usuario no tiene el rol de consultas (Sofibot.Consultas). Pídelo a sistemas.</p>'
    greeting = f"Hola, {escape(who.name.split(' ')[0])}" if entra and who.name else "Explorar Sofibot"
    body = f"""<h1>{greeting}</h1><p class="meta">Qué puedes hacer con Sofibot según tus permisos.</p>
<div class="cards">
<article class="card big"><h2>Informes</h2><p>Informes web y Excel sobre las tablas Gold: los publicados que
puedes ver y los que creas con tu asistente de IA, que nunca ve los datos.</p>
<div class="actions">{''.join(report_actions)}</div></article>
<article class="card big{'' if querier and query_url() else ' off'}"><h2>Consultas</h2>{query_card}</article>
</div>"""
    return ui.page(request, "Explorar", body, active="explore")


# --- Reports (functionality 1) ------------------------------------------------------------

def visible_reports(request: Request) -> list[dict]:
    user = auth.current_user(request)
    permissions = access.load() if user is not None else None
    return [report for report in projects.built() if access.visible(user, report["tables"], permissions)]


@router.get("/informes", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
def reports_page(request: Request):
    who = ui.user(request)
    authors = {d["slug"]: {d.get("created_by"), d.get("submitted_by")} for d in drafts.list_drafts()}
    cards = []
    for report in visible_reports(request):
        mine = who is not None and who.email in authors.get(report["slug"], set())
        links = [f'<a class="button primary" href="{escape(report["html"])}">Ver informe</a>'] if report["html"] else []
        links += [f'<a class="button" href="{escape(url)}" download>Excel · {escape(url.rsplit("/", 1)[-1])}</a>'
                  for url in report["excel"]]
        built = datetime.fromtimestamp(report["built_at"]).strftime("%d/%m/%Y %H:%M")
        tag = '<span class="tag mine">Mío</span>' if mine else ""
        cards.append(f'<article class="card"><h3>{escape(report["name"])}{tag}</h3>'
                     f'<p>{escape(report["description"])}</p><p class="meta">Actualizado {built}</p>'
                     f'<div class="actions">{"".join(links)}</div></article>')
    if cards:
        listing = f'<div class="cards">{"".join(cards)}</div>'
    elif who is None:
        listing = "<p>Todavía no hay informes generados. Ver <code>docs/04-crear-informes.md</code>.</p>"
    else:
        listing = "<p>No tienes acceso a ningún informe. Si lo necesitas, pide acceso a sistemas.</p>"
    body = f"<h1>Informes</h1><p class='meta'>Los informes publicados que puedes ver.</p>{listing}{create_section(who)}"
    return ui.page(request, "Informes", body, active="informes")


def create_section(who) -> str:
    if drafts.api_mode() == "off":
        return ""
    if who is not None and ROLE_AUTHOR not in who.roles:
        return ('<h2 id="crear">Crear informes</h2><p class="meta">Para crear informes con tu asistente de IA '
                'necesitas el rol de autor (Sofibot.Autor). Pídelo a sistemas.</p>')
    rows = []
    for draft in drafts.list_drafts():
        if who is not None and who.email not in (draft.get("created_by"), draft.get("submitted_by")):
            continue
        comment = f'<br><span class="meta">Comentario: {escape(draft["comment"])}</span>' if draft.get("comment") else ""
        rows.append(f'<tr><td>{escape(draft["name"] or draft["slug"])}{comment}</td>'
                    f'<td>{escape(STATUS.get(draft["status"], draft["status"]))}</td>'
                    f'<td>{escape(", ".join(draft.get("tables", [])))}</td></tr>')
    table = ("<div class='scroll'><table><tr><th>Borrador</th><th>Estado</th><th>Tablas</th></tr>" + "".join(rows)
             + "</table></div>") if rows else "<p>Todavía no tienes borradores.</p>"
    return f"""<h2 id="crear">Crear informes con tu IA</h2>
<p>Pide el informe a Claude o Codex en lenguaje normal: <em>«un informe de ventas por tienda de los últimos 12 meses,
con Excel»</em>. Tu asistente solo ve la estructura de tus tablas, nunca los datos. Escribe un borrador y, cuando se lo
digas, lo envía a revisión; un revisor lo previsualiza y lo publica.</p>
<div class="actions"><a class="button primary" href="/conectar#informes">Conectar tu IA</a></div>
<h3>Mis borradores</h3>{table}"""


# --- Queries (functionality 2) ------------------------------------------------------------

def call_query_service(method: str, route: str, token: str, payload: dict | None = None):
    import requests

    response = requests.request(method, f"{query_url()}/api/query{route}", json=payload, timeout=60,
                                headers={"Authorization": f"Bearer {token}", "X-Sofibot-Channel": "portal"},
                                allow_redirects=False)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body


def cell(value, kind: str | None) -> str:
    if value is None:
        return '<span class="meta">Sin datos</span>'
    if isinstance(value, str) and ISO_DATE.fullmatch(value):
        moment = datetime.fromisoformat(value)
        return escape(display_value(moment, "month" if moment.day == 1 and not value[10:] else "date", "es"))
    return escape(display_value(value, kind, "es"))


@router.get("/consultas", response_class=HTMLResponse)
def queries_page(request: Request):
    who = ui.user(request)
    connect = '<p class="meta">También puedes preguntar desde Claude o Codex: <a href="/conectar#consultas">conecta tu IA</a>.</p>'

    def show(message: str, extra: str = ""):
        return ui.page(request, "Consultas", f"<h1>Consultas</h1>{ui.notice(message)}{extra}", active="consultas")

    if not query_url():
        return show("El servicio de consultas no está activado en esta instalación (docs/11-consultas.md).")
    if who is None:
        return show("Las consultas necesitan el inicio de sesión con Microsoft Entra ID.")
    if ROLE_QUERY not in who.roles:
        return show("Tu usuario no tiene el rol de consultas (Sofibot.Consultas). Pídelo a sistemas.")
    token = auth.api_token(request)
    if token is None:
        return show("Tu sesión para consultas ha caducado.",
                    '<div class="actions"><a class="button primary" href="/auth/login?next=/consultas">Volver a entrar</a></div>')
    try:
        status, catalog = call_query_service("GET", "/catalog", token)
    except Exception:
        return show("El servicio de consultas no responde. Avisa a sistemas.")
    if status != 200:
        return show(f"El servicio de consultas ha rechazado la petición: {catalog.get('detail', status)}")
    tables = catalog.get("tables", {})
    if not tables:
        return show("No tienes tablas consultables: tus roles no incluyen ninguna tabla del catálogo.", connect)
    params = request.query_params
    table = params.get("tabla") if params.get("tabla") in tables else next(iter(tables))
    spec = tables[table]
    chosen_measures = [m for m in params.getlist("m") if m in spec["measures"]]
    chosen_dims = [d for d in params.getlist("d") if d in spec["dimensions"]]
    result_html = ""
    if params.get("run") and chosen_measures:
        payload = {"table": table, "measures": chosen_measures, "dimensions": chosen_dims}
        if spec.get("has_period") and params.get("desde") and params.get("hasta"):
            payload["period"] = {"from": params["desde"], "to": params["hasta"]}
        values = [v.strip() for v in params.get("fval", "").split(",") if v.strip()]
        if params.get("fdim") in spec["dimensions"] and values:
            payload["filters"] = [{"dimension": params["fdim"], "values": values}]
        if params.get("orden") in chosen_measures + chosen_dims:
            payload["order"] = {"by": params["orden"], "desc": params.get("asc") != "1"}
        if params.get("limite", "").isdigit():
            payload["limit"] = int(params["limite"])
        result_html = run_and_render(token, payload, spec)
    elif params.get("run"):
        result_html = ui.notice("Elige al menos una medida.")
    body = f"""<h1>Consultas</h1><p class="meta">Medidas por dimensiones de las tablas que tus roles permiten.
Las consultas quedan registradas (quién y qué se pidió, nunca los valores).</p>
{query_form(tables, table, spec, chosen_measures, chosen_dims, params)}{result_html}{connect}"""
    return ui.page(request, "Consultas", body, active="consultas")


def query_form(tables, table, spec, measures, dims, params) -> str:
    def options(items, selected):
        return "".join(f'<option value="{escape(k)}"{" selected" if k == selected else ""}>{escape(label)}</option>'
                       for k, label in items)

    def boxes(name, entries, chosen):
        return "".join(f'<label><input type="checkbox" name="{name}" value="{escape(k)}"{" checked" if k in chosen else ""}> '
                       f'{escape(k)} <span class="meta">{escape(v.get("description", ""))}</span></label>'
                       for k, v in entries.items())

    dims_items = [("", "—")] + [(k, k) for k in spec["dimensions"]]
    order_items = [("", "—")] + [(k, k) for k in [*spec["measures"], *spec["dimensions"]]]
    period = ""
    if spec.get("has_period"):
        period = (f'<fieldset><legend>Periodo (meses completos)</legend>'
                  f'<label>Desde <input type="month" name="desde" value="{escape(params.get("desde", ""))}"></label>'
                  f'<label>Hasta <input type="month" name="hasta" value="{escape(params.get("hasta", ""))}"></label></fieldset>')
    rules = "".join(f"<li>{escape(rule)}</li>" for rule in spec.get("rules", []))
    return f"""<form class="grid" method="get" action="/consultas">
<label>Tabla <select name="tabla">{options([(k, k) for k in tables], table)}</select></label>
<p class="meta" style="grid-column:span 2">{escape(spec.get("description", ""))}{f"<ul>{rules}</ul>" if rules else ""}</p>
<fieldset><legend>Medidas</legend>{boxes("m", spec["measures"], measures)}</fieldset>
<fieldset><legend>Agrupar por</legend>{boxes("d", spec["dimensions"], dims) or '<span class="meta">Sin dimensiones</span>'}</fieldset>
{period}
<fieldset><legend>Filtro</legend><label>Dimensión <select name="fdim">{options(dims_items, params.get("fdim", ""))}</select></label>
<label>Valores, separados por comas <input type="text" name="fval" value="{escape(params.get("fval", ""))}"></label></fieldset>
<fieldset><legend>Orden y límite</legend><label>Ordenar por <select name="orden">{options(order_items, params.get("orden", ""))}</select></label>
<label><input type="checkbox" name="asc" value="1"{" checked" if params.get("asc") == "1" else ""}> Ascendente</label>
<label>Filas máximas <input type="number" min="1" name="limite" value="{escape(params.get("limite", ""))}"></label></fieldset>
<div class="actions"><button class="primary" name="run" value="1">Consultar</button>
<span class="meta">Si cambias de tabla, pulsa Consultar para ver sus medidas.</span></div></form>"""


def run_and_render(token: str, payload: dict, spec: dict) -> str:
    try:
        status, result = call_query_service("POST", "", token, payload)
    except Exception:
        return ui.notice("El servicio de consultas no responde. Avisa a sistemas.")
    if status != 200:
        detail = result.get("detail", status)
        return ui.notice(f"No se ha podido consultar: {detail.get('message') if isinstance(detail, dict) else detail}")
    kinds = {name: spec["measures"].get(name, {}).get("format") for name in result["columns"]}
    head = "".join(f"<th>{escape(c)}</th>" for c in result["columns"])
    rows = "".join("<tr>" + "".join(f'<td class="{"num" if kinds.get(c) else ""}">{cell(v, kinds.get(c))}</td>'
                                    for c, v in zip(result["columns"], row)) + "</tr>" for row in result["rows"])
    period = result.get("period")
    summary = (f'{escape(", ".join(payload["measures"]))}'
               f'{" por " + escape(", ".join(payload["dimensions"])) if payload["dimensions"] else ""}'
               f' · {escape(result["table"])}'
               f'{" · " + escape(period["from"]) + " a " + escape(period["to"]) if period else " · todo el periodo"}')
    more = ui.notice("Hay más filas que el límite: afina la consulta o súbelo.") if result.get("truncated") else ""
    return (f'<h2>Resultado</h2><p class="meta">{summary} · {len(result["rows"])} filas</p>{more}'
            f'<div class="scroll"><table><tr>{head}</tr>{rows}</table></div>')


# --- Connect your AI ----------------------------------------------------------------------

def mcp_settings() -> dict:
    return {"SOFIBOT_URL": os.environ.get("SOFIBOT_PUBLIC_URL", "https://informes.empresa.local").rstrip("/"),
            "SOFIBOT_ENTRA_TENANT_ID": os.environ.get("ENTRA_TENANT_ID", "<id. de inquilino>"),
            "SOFIBOT_ENTRA_CLIENT_ID": os.environ.get("ENTRA_CLIENT_ID", "<id. de cliente>")}


FOLDER = r"C:\sofibot-mcp"


def exe_file():
    """The Windows program with both connectors (mcp-server/build-exe.ps1), if this installation has it."""
    path = config.MCP_DIR / "dist" / "sofibot-mcp.exe"
    return path if path.is_file() else None


def snippets(name: str, mode: str, ai: str, url: str | None = None, exe: bool = True) -> dict[str, str]:
    """Configuration for Claude Code, Claude Desktop and Codex. mode: informes | consultas."""
    if exe:
        command, args = rf"{FOLDER}\sofibot-mcp.exe", [mode]
    else:
        command, args = rf"{FOLDER}\.venv\Scripts\python.exe", [rf"{FOLDER}\sofibot_{mode}_mcp.py"]
    env = {**mcp_settings(), "SOFIBOT_AI": ai}
    if url:
        env["SOFIBOT_URL"] = url
    claude = {"mcpServers": {name: {"command": command, "args": args, "env": env}}}
    toml_env = ", ".join(f'{k} = "{v}"' for k, v in env.items())
    toml_args = ", ".join(f"'{a}'" for a in args)
    codex = (f"[mcp_servers.{name.replace('-', '_')}]\ncommand = '{command}'\nargs = [{toml_args}]\n"
             f"env = {{ {toml_env} }}\nstartup_timeout_sec = 30\ntool_timeout_sec = 120")
    cli = (f"claude mcp add {name} --scope user " + " ".join(f"-e {k}={v}" for k, v in env.items())
           + f" -- {command} {' '.join(args)}")
    return {"Claude Code (terminal)": cli, "Claude Desktop (claude_desktop_config.json)": json.dumps(claude, indent=2),
            "Codex (~/.codex/config.toml)": codex}


def connection_settings() -> dict:
    """What the connector installer needs: public addresses and ids only, never a secret."""
    url = os.environ.get("SOFIBOT_PUBLIC_URL", "").strip().rstrip("/")
    return {"url": url, "tenant_id": os.environ.get("ENTRA_TENANT_ID", "").strip(),
            "client_id": os.environ.get("ENTRA_CLIENT_ID", "").strip(),
            "informes": drafts.api_mode() == "entra", "consultas": bool(query_url()),
            "query_url": os.environ.get("SOFIBOT_QUERY_PUBLIC_URL", "").strip().rstrip("/") or url}


@router.get("/conexion.json")
def connection_file():
    """Public on purpose (the sign-in page already shows these ids): lets the installer find Sofibot."""
    return connection_settings()


AIS = [("Claude Desktop", "https://claude.ai/download",
        "La aplicación de escritorio de Claude. La más sencilla para la mayoría de personas."),
       ("Claude Code", "https://docs.anthropic.com/en/docs/claude-code/setup",
        "Claude en la terminal o en VS Code. Para perfiles técnicos y para crear informes."),
       ("Codex", "https://github.com/openai/codex", "El asistente de OpenAI, en la terminal o en VS Code.")]


@router.get("/conectar", response_class=HTMLResponse)
def connect_page(request: Request):
    who = ui.user(request)
    exe = exe_file() is not None
    settings = connection_settings()
    mine = []
    if settings["informes"] and (who is None or ROLE_AUTHOR in who.roles):
        mine.append("crear informes (tu IA ve solo la estructura de tus tablas, nunca datos)")
    if settings["consultas"] and (who is None or ROLE_QUERY in who.roles):
        mine.append("consultar datos de tus tablas (tu IA recibe los resultados)")
    if not mine:
        body = ("<h1>Conectar tu IA</h1>" + ui.notice(
            "Tu usuario no tiene ningún conector disponible: pide a sistemas el rol de autor de informes "
            "(Sofibot.Autor) o de consultas (Sofibot.Consultas)."))
        return ui.page(request, "Conectar tu IA", body, active="conectar")
    ais = "".join(f'<article class="card"><h3>{escape(name)}</h3><p>{escape(text)}</p>'
                  f'<div class="actions"><a class="button" href="{escape(link)}" target="_blank" rel="noopener">'
                  f'Cómo instalarlo</a></div></article>' for name, link, text in AIS)
    if exe:
        automatic = """<h2>2 · Conectar automáticamente</h2>
<div class="actions"><a class="button primary" href="/descargas/sofibot-conectar.zip">Descargar el conector de Sofibot</a></div>
<ol><li>Abre el fichero descargado (<code>sofibot-conectar.zip</code>) y pulsa <b>Extraer todo</b>.</li>
<li>En la carpeta extraída, haz <b>doble clic en <code>sofibot-mcp.exe</code></b>. Si Windows avisa de que el programa
no es conocido: <em>Más información → Ejecutar de todas formas</em>.</li>
<li>Lee lo que va a hacer y pulsa <b>Enter</b>. Se abrirá el navegador para iniciar sesión con tu cuenta de Microsoft.</li>
<li>Cuando diga <b>Listo</b>, cierra y vuelve a abrir Claude o Codex.</li></ol>
<details><summary>Qué hace exactamente el conector</summary>
<ul><li>Se copia a <code>%LOCALAPPDATA%\\Sofibot\\sofibot-mcp.exe</code>. No necesita permisos de administrador ni instala nada más.</li>
<li>Te pide iniciar sesión con Microsoft y pregunta a Sofibot qué puedes usar con tus roles.</li>
<li>Busca tus IAs y añade los conectores de Sofibot a su configuración, guardando antes una copia de cada fichero
(<code>….antes-de-sofibot-&lt;fecha&gt;</code>):
<ul><li>Claude Desktop: <code>%APPDATA%\\Claude\\claude_desktop_config.json</code></li>
<li>Claude Code: <code>%USERPROFILE%\\.claude.json</code></li>
<li>Codex: <code>%USERPROFILE%\\.codex\\config.toml</code></li></ul></li>
<li>Lo que escribe son la dirección de Sofibot y los identificadores públicos de la empresa en Microsoft: ninguna
contraseña. Tu sesión de Microsoft queda en <code>%USERPROFILE%\\.sofibot\\</code>, solo en este equipo.</li>
<li>Antes de cambiar nada te muestra la lista; con <b>D</b> ves el texto exacto que añade, y con <b>C</b> cancelas.</li>
<li>Si instalas otra IA más adelante, vuelve a abrir <code>%LOCALAPPDATA%\\Sofibot\\sofibot-mcp.exe</code>.</li></ul></details>"""
    else:
        automatic = """<h2>2 · Conectar</h2><p class="meta">Esta instalación todavía no incluye el conector automático
(<code>sofibot-mcp.exe</code>): usa la configuración manual de abajo, con Python 3.12.</p>"""

    def manual(name, mode, role, available, url=None):
        if not available or (who is not None and role not in who.roles):
            return ""
        parts = "".join(f"<h4>{escape(label)}</h4><pre><code>{escape(text)}</code></pre>"
                        for label, text in snippets(name, mode, "claude", url, exe).items())
        return f"<h3>Conector de {mode}</h3>{parts}"

    where = (f"""<p>{'Guarda <a href="/descargas/sofibot-mcp.exe">sofibot-mcp.exe</a> en <code>C:\\sofibot-mcp\\</code>.'
              if exe else 'Descarga <a href="/descargas/sofibot-mcp.zip">los conectores en Python</a>, descomprímelos en '
              '<code>C:\\sofibot-mcp</code> y, con Python 3.12, ejecuta allí <code>python -m venv .venv</code> y '
              '<code>.venv\\Scripts\\pip install -r requirements.txt</code>.'} Después, según tu IA:</p>
<ul><li><b>Claude Desktop</b>: menú <em>Configuración → Desarrollador → Editar configuración</em>. Se abre la carpeta
con <code>claude_desktop_config.json</code>: ábrelo con el Bloc de notas, pega el bloque de Claude Desktop (si ya tiene
<code>"mcpServers"</code>, añade solo las entradas de Sofibot dentro), guarda y reinicia Claude.</li>
<li><b>Claude Code</b>: copia el comando de Claude Code en PowerShell y pulsa Enter.</li>
<li><b>Codex</b>: abre <code>%USERPROFILE%\\.codex\\config.toml</code> con el Bloc de notas (créalo si no existe),
pega el bloque de Codex al final, cambia <code>SOFIBOT_AI</code> a <code>codex</code> y guarda.</li></ul>""")
    blocks = (manual("sofibot-informes", "informes", ROLE_AUTHOR, settings["informes"])
              + manual("sofibot-consultas", "consultas", ROLE_QUERY, settings["consultas"],
                       os.environ.get("SOFIBOT_QUERY_PUBLIC_URL", "").strip().rstrip("/") or None))
    body = f"""<h1>Conectar tu IA</h1>
<p>Usa Sofibot desde la IA con la que ya trabajas. Con tus permisos podrás: {"; ".join(escape(m) for m in mine)}.</p>
<h2>1 · Ten instalada tu IA</h2><p class="meta">Si ya tienes una, pasa al paso 2.</p><div class="cards">{ais}</div>
{automatic}
<h2>3 · Probarlo</h2><p>En Claude o Codex, pregunta: <em>«¿Qué puedo consultar en Sofibot?»</em> o
<em>«Crea en Sofibot un informe de ventas por mes con Excel»</em>. La primera vez puede pedirte iniciar sesión.</p>
<details{" open" if not exe else ""}><summary><b>Configuración manual (avanzado)</b></summary>{where}{blocks}</details>
<p class="meta">Los datos que consulta tu IA llegan a su proveedor: úsala solo con la cuenta de IA que autorice la empresa.</p>"""
    return ui.page(request, "Conectar tu IA", body, active="conectar")


@router.get("/descargas/sofibot-conectar.zip")
def download_connector():
    path = exe_file()
    if path is None:
        return Response("Esta instalación no incluye sofibot-mcp.exe: usa la configuración manual.", status_code=404)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(path, "sofibot-conectar/sofibot-mcp.exe")
        archive.writestr("sofibot-conectar/sofibot-conexion.json", json.dumps(connection_settings(), indent=2))
        archive.writestr("sofibot-conectar/LEEME.txt",
                         "Haz doble clic en sofibot-mcp.exe y sigue las instrucciones.\r\n"
                         "Conecta Claude o Codex con Sofibot. Más detalles en la página 'Conectar tu IA' de Sofibot.\r\n")
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="sofibot-conectar.zip"'})


@router.get("/descargas/sofibot-mcp.zip")
def download_mcp():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in MCP_FILES:
            path = config.MCP_DIR / name
            if path.is_file():
                archive.write(path, f"sofibot-mcp/{name}")
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="sofibot-mcp.zip"'})


@router.get("/descargas/sofibot-mcp.exe")
def download_exe():
    path = exe_file()
    if path is None:
        return Response("Esta instalación no incluye sofibot-mcp.exe: usa los conectores en Python.", status_code=404)
    return FileResponse(path, media_type="application/vnd.microsoft.portable-executable", filename="sofibot-mcp.exe")


LANDING = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sofibot</title><style>""" + ui.STYLE + """
.hero{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
background:linear-gradient(135deg,#2C3968 0%,#2C3968 55%,#279CDB 100%);color:#fff}
.hero section{max-width:560px}.hero h1{font-size:40px;margin:0 0 8px;font-weight:500}.hero p{font-size:17px;opacity:.92}
.hero .button{background:#fff;color:#2C3968;border:0;padding:12px 20px;font-size:16px;margin-top:16px}
.hero ul{padding-left:18px;opacity:.92}.hero .bar{width:64px;height:5px;background:#D16B1B;border-radius:3px;margin-bottom:18px}
</style></head><body><div class="hero"><section><div class="bar"></div><h1>Sofibot</h1>
<p>Informes y consultas sobre los datos de la empresa, con inteligencia artificial y con los permisos de cada persona.</p>
<ul><li>Informes web y Excel publicados para ti.</li><li>Crea informes con tu asistente de IA, sin que vea los datos.</li>
<li>Pregunta a los datos de tus tablas, al momento.</li></ul>
<a class="button" href="/auth/login?next=/explore">Iniciar sesión con Microsoft</a>
<p class="meta" style="color:#fff;opacity:.75">Usa tu cuenta de la empresa.</p></section></div></body></html>"""

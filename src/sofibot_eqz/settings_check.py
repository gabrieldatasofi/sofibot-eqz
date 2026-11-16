"""sofibot config: which settings are filled in and which are missing, never their values.

Its output can be pasted to anyone, including an AI assistant guiding the installation
(INSTALAR-CON-IA.md): it shows only variable names, "filled in" or "missing", and the few
settings that are modes (sql/entra, on/off, the Gold schema name), never a host, a user, a
password, a token or a URL.
"""
import os

from . import auth, drafts
from .db import AUTH_MODES

FILLED, MISSING, SHORT = "rellena", "FALTA", "DEMASIADO CORTA"
# Settings that are a mode, not an address or a secret: their value may be shown.
SHOWN = ("SQLSERVER_AUTH", "SQLSERVER_GOLD_SCHEMA", "SQLSERVER_ENCRYPT", "SQLSERVER_TRUST_CERTIFICATE",
         "SOFIBOT_BIND", "SOFIBOT_QUERY_ENABLED")


def _status(env, name: str, minimum: int = 1) -> str:
    value = env.get(name, "").strip()
    if not value:
        return MISSING
    return SHORT if len(value) < minimum else FILLED


def _sql(env, lines: list, problems: list) -> None:
    sql_auth = env.get("SQLSERVER_AUTH", "sql").strip() or "sql"
    if sql_auth not in AUTH_MODES:
        problems.append(f"SQLSERVER_AUTH debe ser {' | '.join(AUTH_MODES)}")
    lines.append("SQL Server")
    names = ["SQLSERVER_HOST", "SQLSERVER_DATABASE"]
    if sql_auth != "windows":
        names += ["SQLSERVER_USER", "SQLSERVER_PASSWORD"]
    for name in names:
        status = _status(env, name)
        lines.append(f"  {name:32} {status}")
        if status == MISSING:
            problems.append(f"{name} está vacía")
    for name in SHOWN[:4]:
        default = {"SQLSERVER_AUTH": "sql", "SQLSERVER_GOLD_SCHEMA": "gold", "SQLSERVER_ENCRYPT": "yes",
                   "SQLSERVER_TRUST_CERTIFICATE": "0"}[name]
        lines.append(f"  {name:32} {env.get(name, '').strip() or default}")
    if env.get("SQLSERVER_TRUST_CERTIFICATE", "").strip() == "1":
        lines.append("  Aviso: SQLSERVER_TRUST_CERTIFICATE=1 solo es para un SQL Server de prueba")


def review(env=os.environ, service: str = "portal") -> tuple[list[str], list[str]]:
    """Return (lines to print, problems). Values never appear, except the modes in SHOWN."""
    lines: list[str] = []
    problems: list[str] = []
    if service == "consultas":
        enabled = env.get("SOFIBOT_QUERY_ENABLED", "").strip() == "1"
        lines.append(f"Servicio de consultas: {'activado' if enabled else 'DESACTIVADO'} (SOFIBOT_QUERY_ENABLED)")
        if not enabled:
            problems.append("SOFIBOT_QUERY_ENABLED debe ser 1")
        _sql(env, lines, problems)
        if env.get("SQLSERVER_USER", "").strip().lower() == "sofibot_lectura":
            problems.append("las consultas usan su propio login (sofibot_consultas), no el del portal")
        lines.append("Entra ID")
        for name in ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID"):
            status = _status(env, name)
            lines.append(f"  {name:32} {status}")
            if status == MISSING:
                problems.append(f"{name} está vacía")
        return lines, problems

    _sql(env, lines, problems)
    lines.append("Portal")
    status = _status(env, "SOFIBOT_ADMIN_TOKEN", 32)
    lines.append(f"  {'SOFIBOT_ADMIN_TOKEN':32} {status}")
    if status != FILLED:
        problems.append("SOFIBOT_ADMIN_TOKEN necesita 32 caracteres o más")
    bind = env.get("SOFIBOT_BIND", "").strip() or "127.0.0.1"
    lines.append(f"  {'SOFIBOT_BIND':32} {bind}")

    try:
        sign_in = auth.mode(env)
    except RuntimeError as exc:
        sign_in = "?"
        problems.append(str(exc))
    lines.append(f"  {'Inicio de sesión (SOFIBOT_AUTH)':32} {sign_in}")
    if sign_in == "basic":
        lines.append(f"  {'SOFIBOT_VIEWER_PASSWORD':32} {_status(env, 'SOFIBOT_VIEWER_PASSWORD')}")
    if sign_in == "entra":
        for name in ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET", "SOFIBOT_PUBLIC_URL"):
            status = _status(env, name)
            lines.append(f"  {name:32} {status}")
            if status == MISSING:
                problems.append(f"SOFIBOT_AUTH=entra necesita {name}")
        url = env.get("SOFIBOT_PUBLIC_URL", "").strip()
        if url and not url.startswith(("https://", "http://localhost")):
            problems.append("SOFIBOT_PUBLIC_URL debe empezar por https://")
    if sign_in == "none":
        lines.append("  Aviso: sin inicio de sesión, cualquiera que llegue al portal ve todos los informes")

    try:
        code_api = drafts.api_mode(env)
    except drafts.DraftError as exc:
        code_api = "?"
        problems.append(str(exc))
    lines.append(f"  {'API de informes (SOFIBOT_CODE_API)':32} {code_api}")
    if code_api == "token":
        token = env.get("SOFIBOT_API_TOKEN", "").strip()
        ok = len(token) >= 32 and token != env.get("SOFIBOT_ADMIN_TOKEN", "").strip()
        lines.append(f"  {'SOFIBOT_API_TOKEN':32} {FILLED if ok else MISSING + ' o igual al de administración'}")
        if not ok:
            problems.append("SOFIBOT_API_TOKEN necesita 32 caracteres o más y ser distinto de SOFIBOT_ADMIN_TOKEN")
    if code_api == "entra" and sign_in != "entra":
        problems.append("SOFIBOT_CODE_API=entra necesita también SOFIBOT_AUTH=entra")
    queries = bool(env.get("SOFIBOT_QUERY_URL", "").strip())
    lines.append(f"  {'Página Consultas (SOFIBOT_QUERY_URL)':32} {'activada' if queries else 'desactivada'}")
    return lines, problems

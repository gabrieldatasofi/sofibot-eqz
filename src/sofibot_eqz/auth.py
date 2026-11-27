"""Sign-in to the portal, chosen with SOFIBOT_AUTH:

- none: open portal (only for a server nobody else can reach);
- basic: one shared user and password (SOFIBOT_VIEWER_USER / SOFIBOT_VIEWER_PASSWORD);
- entra: each person signs in with their Microsoft Entra ID account (OpenID Connect,
  authorization code flow with PKCE, through Microsoft's MSAL library). Entra ID only says
  who they are; their roles, and so what they see, come from acceso/usuarios.json (access.py).
  Local accounts (acceso/cuentas-locales.json), if there are any, can also sign in: the
  emergency administrator that does not depend on Entra ID;
- local: only local accounts, with a user name and password; no Entra ID at all.

Local accounts are of two kinds: user name and password (acceso/cuentas-locales.json), or user
name, password and then a TOTP code from an authenticator app (acceso/cuentas-totp.json).
SOFIBOT_LOCAL_ACCOUNTS chooses which kinds may sign in (both by default). A TOTP account created
from the administration page starts with a temporary password: at its first sign-in its owner
chooses a password and scans the QR code (/auth/activar), so only they ever see the secret.

Without SOFIBOT_AUTH: basic if SOFIBOT_VIEWER_PASSWORD is set, none otherwise. "entra" and
"local" are the per-user modes: each person has roles, the administration page exists.

With Entra ID and the query service configured (SOFIBOT_QUERY_URL), sign-in also obtains an
access token for Sofibot's own API (scope SOFIBOT_API_SCOPE), so that the portal's query page
can forward a user's query to the query service as that user. The token is kept in this
process's memory, keyed by a random id in the session cookie; never in the cookie itself.
"""
from collections import defaultdict, deque
from dataclasses import dataclass
import functools
from html import escape
import logging
import os
import secrets
import threading
import time
from urllib.parse import parse_qs, quote
import warnings

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from . import access, identity

MODES = ("none", "basic", "entra", "local")
PER_USER = ("entra", "local")
# Local sign-in: after this many wrong passwords in the window, for a name or an address, wait.
FAILURES, WINDOW = 5, 15 * 60
_failures: dict[str, deque] = defaultdict(deque)
_failures_lock = threading.Lock()
# TOTP: minutes between the password and the code; the last step accepted per account (one use).
TOTP_MINUTES = 5
_used_steps: dict[str, int] = {}
_used_steps_lock = threading.Lock()
# Activation: minutes to finish it; the new secret waits in this process's memory, not in the cookie.
ACTIVATION_MINUTES = 15
_activation_secrets: dict[str, tuple[str, float]] = {}
_activation_lock = threading.Lock()
log = logging.getLogger("sofibot")
# MSAL suggests response_mode=form_post. Its callback is a cross-site POST, which would need a
# SameSite=None session cookie; the code in the query is single-use and bound to PKCE and the secret.
warnings.filterwarnings("ignore", message="response_mode='form_post' is recommended")
router = APIRouter(prefix="/auth")
_api_tokens: dict[str, tuple[str, float]] = {}
_api_tokens_lock = threading.Lock()


def api_scope(env=os.environ) -> str | None:
    """The scope for Sofibot's own API, requested only when the portal forwards queries."""
    if not env.get("SOFIBOT_QUERY_URL", "").strip():
        return None
    return env.get("SOFIBOT_API_SCOPE", "").strip() or f"api://{env.get('ENTRA_CLIENT_ID', '').strip()}/access_as_user"


def keep_api_token(request: Request, result: dict) -> None:
    token, lifetime = result.get("access_token"), int(result.get("expires_in") or 0)
    if not token:
        return
    key = secrets.token_urlsafe(24)
    now = time.time()
    with _api_tokens_lock:
        for old in [k for k, (_, expires) in _api_tokens.items() if expires < now]:
            del _api_tokens[old]
        _api_tokens[key] = (token, now + lifetime - 120)
    request.session["api"] = key


def api_token(request: Request) -> str | None:
    """The signed-in user's token for Sofibot's API, or None (not requested, expired, restarted).

    For a local account, a short Sofibot token made now (none without SOFIBOT_LOCAL_SECRET)."""
    user = request.session.get("user") or {}
    if user.get("local"):
        account = local_account(user)
        if account is None or identity.local_secret() is None:
            return None
        return identity.issue_token(user["email"], account, minutes=15)
    key = request.session.get("api")
    with _api_tokens_lock:
        token, expires = _api_tokens.get(key, (None, 0.0)) if key else (None, 0.0)
    return token if token and expires > time.time() else None


def forget_api_token(request: Request) -> None:
    key = request.session.get("api")
    if key:
        with _api_tokens_lock:
            _api_tokens.pop(key, None)


def mode(env=os.environ) -> str:
    value = env.get("SOFIBOT_AUTH", "").strip().lower()
    if not value:
        return "basic" if env.get("SOFIBOT_VIEWER_PASSWORD") else "none"
    if value not in MODES:
        raise RuntimeError(f"SOFIBOT_AUTH must be one of {', '.join(MODES)}")
    return value


def per_user(env=os.environ) -> bool:
    """Each person signs in and has roles (Entra ID and/or local accounts)."""
    return mode(env) in PER_USER


def local_accounts_on(env=os.environ) -> bool:
    """The sign-in page offers user name and password: local mode, or Entra with local accounts."""
    return mode(env) == "local" or (mode(env) == "entra" and bool(access.load_local_accounts()))


def local_account(user: dict) -> dict | None:
    """The account of a local session, while it exists and its password has not changed."""
    account = access.load_local_accounts().get(user.get("email", ""))
    if account is None or access.pending(account) or account["version"] != user.get("v"):
        return None
    return account


def check_settings(env=os.environ) -> str:
    """Fail at start-up, with the variable to fix, rather than on the first sign-in."""
    current = mode(env)
    if current == "basic" and not env.get("SOFIBOT_VIEWER_PASSWORD"):
        raise RuntimeError("SOFIBOT_AUTH=basic needs SOFIBOT_VIEWER_PASSWORD")
    if current == "entra":
        EntraSettings.from_environment(env)
    try:
        access.enabled_kinds(env)
    except access.PermissionsError as exc:
        raise RuntimeError(str(exc)) from exc
    return current


@dataclass(frozen=True)
class EntraSettings:
    tenant_id: str
    client_id: str
    client_secret: str
    public_url: str

    @classmethod
    def from_environment(cls, env=os.environ) -> "EntraSettings":
        names = ["ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET", "SOFIBOT_PUBLIC_URL"]
        missing = [name for name in names if not env.get(name, "").strip()]
        if missing:
            raise RuntimeError(f"SOFIBOT_AUTH=entra needs {', '.join(missing)} (docs/09-inicio-sesion-entra.md)")
        public_url = env["SOFIBOT_PUBLIC_URL"].strip().rstrip("/")
        if not public_url.startswith(("https://", "http://localhost")):
            raise RuntimeError("SOFIBOT_PUBLIC_URL must start with https:// (Entra ID requires HTTPS)")
        return cls(env["ENTRA_TENANT_ID"].strip(), env["ENTRA_CLIENT_ID"].strip(),
                   env["ENTRA_CLIENT_SECRET"].strip(), public_url)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/callback"


@functools.cache
def _client(settings: EntraSettings):
    import msal

    return msal.ConfidentialClientApplication(
        settings.client_id, client_credential=settings.client_secret,
        authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
    )


def current_user(request: Request) -> dict | None:
    """The signed-in user (Entra or local), or None when the portal has no per-user sign-in."""
    if not per_user():
        return None
    # The sign-in middleware only lets signed-in users through; an empty user sees nothing.
    user = dict(request.session.get("user") or {"name": "", "email": ""})
    if user.get("local"):
        # A local account carries its own roles (acceso/cuentas-locales.json), read on every request.
        account = local_account(user) if mode() in PER_USER else None
        user["roles"] = list(account["roles"]) if account else []
        return user
    # Roles come from acceso/usuarios.json on every request, never from Entra: a change applies at once.
    user["roles"] = list(access.roles_of(user.get("email", ""))) if mode() == "entra" else []
    return user


def session_valid(request: Request) -> bool:
    """A signed-in session that still counts: Entra only in entra mode; local while the account lasts."""
    user = request.session.get("user")
    if not user:
        return False
    if user.get("local"):
        return local_account(user) is not None
    return mode() == "entra"


def safe_next(value: str | None) -> str:
    """Only paths on this site: '//host' or '/\\host' would send the user elsewhere."""
    if not value or not value.startswith("/") or value.startswith(("//", "/\\")) or any(c < " " for c in value):
        return "/explore"
    return value


@router.get("/login")
def login(request: Request, next: str | None = None, error: str = ""):
    """With local accounts: a page with both ways in. With Entra ID alone: straight to Microsoft."""
    if not local_accounts_on():
        return microsoft(request, next)
    token = request.session.get("login_csrf") or secrets.token_urlsafe(24)
    request.session["login_csrf"] = token
    entra = mode() == "entra"
    message = {"1": "Usuario o contraseña incorrectos.",
               "2": "Demasiados intentos fallidos. Espera unos minutos y vuelve a intentarlo.",
               "3": "El formulario ha caducado: vuelve a intentarlo.",
               "4": "La contraseña temporal de esta cuenta ha caducado. Pide a un administrador de Sofibot que "
                    "la restablezca."}.get(error, "")
    body = LOGIN.format(
        microsoft=(f'<a class="ms" href="/auth/microsoft?next={escape(quote(safe_next(next)))}">Iniciar sesión con Microsoft</a>'
                   '<p class="or">o con una cuenta local de Sofibot</p>') if entra else "",
        error=f'<p class="error" role="alert">{escape(message)}</p>' if message else "",
        csrf=escape(token), next=escape(safe_next(next)))
    return HTMLResponse(PAGE.format(title="Iniciar sesión", message="", action=body).replace("<p></p>", ""),
                        401 if error == "1" else 429 if error == "2" else 200)


def _blocked(keys: list[str], now: float) -> bool:
    with _failures_lock:
        for key in keys:
            recent = _failures[key]
            while recent and now - recent[0] > WINDOW:
                recent.popleft()
        blocked = any(len(_failures[key]) >= FAILURES for key in keys)
        for key in [k for k, recent in _failures.items() if not recent]:
            del _failures[key]  # forget names and addresses with no recent failure
        return blocked


def _failed(keys: list[str], now: float) -> None:
    with _failures_lock:
        for key in keys:
            _failures[key].append(now)


@router.post("/local")
async def local_login(request: Request):
    """Sign in with a local account (acceso/cuentas-locales.json)."""
    if not local_accounts_on():
        return page("Inicio de sesión no disponible", "Esta instalación no tiene cuentas locales.",
                    ("/auth/login", "Volver"), status=404)
    fields = parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
    field = lambda name: (fields.get(name) or [""])[0]  # noqa: E731
    next_path = safe_next(field("next"))
    back = f"/auth/login?next={quote(next_path)}"
    expected = request.session.get("login_csrf", "")
    if not expected or not secrets.compare_digest(field("csrf").encode(), expected.encode()):
        return RedirectResponse(back + "&error=3", 303)
    name = field("usuario").strip().casefold()[:64]
    address = request.client.host if request.client else "?"
    keys, now = [f"user:{name}", f"ip:{address}"], time.monotonic()
    if _blocked(keys, now):
        log.warning("Local sign-in blocked after repeated failures: %s from %s", name, address)
        return RedirectResponse(back + "&error=2", 303)
    # scrypt takes a moment and much memory on purpose: off the event loop.
    account = await run_in_threadpool(identity.local_sign_in, name, field("contrasena"))
    if account is None:
        _failed(keys, now)
        log.warning("Local sign-in failed: %s from %s", name, address)
        return RedirectResponse(back + "&error=1", 303)
    request.session.clear()
    if access.pending(account):
        if access.expired(account):
            log.warning("Local sign-in refused: %s from %s, temporary password expired", name, address)
            return RedirectResponse(back + "&error=4", 303)
        # Right temporary password: now its owner chooses a password and scans the QR code.
        key = secrets.token_urlsafe(24)
        with _activation_lock:
            for old in [k for k, (_, t) in _activation_secrets.items() if time.time() - t > ACTIVATION_MINUTES * 60]:
                del _activation_secrets[old]
            _activation_secrets[key] = (identity.new_totp_secret(), time.time())
        request.session["activar"] = {"user": name, "v": account["version"], "t": time.time(), "next": next_path, "k": key}
        return RedirectResponse("/auth/activar", 303)
    if account["totp"]:
        # Right password: now the code. Until then the session has no user, only this.
        request.session["totp"] = {"user": name, "v": account["version"], "t": time.time(), "next": next_path}
        return RedirectResponse("/auth/codigo", 303)
    return signed_in(request, account, name, address, next_path)


def signed_in(request: Request, account: dict, name: str, address: str, next_path: str):
    request.session.clear()
    request.session["user"] = {"name": account["nombre"], "email": name, "local": True, "v": account["version"]}
    log.info("Signed in with a local account%s: %s from %s, roles %s", " (TOTP)" if account["totp"] else "",
             name, address, ", ".join(account["roles"]))
    return RedirectResponse(next_path, 303)


def pending_totp(request: Request) -> tuple[str, dict, str] | None:
    """(name, account, next) after a right password, for TOTP_MINUTES, while the account is unchanged."""
    pending = request.session.get("totp")
    if not isinstance(pending, dict) or time.time() - float(pending.get("t") or 0) > TOTP_MINUTES * 60:
        return None
    account = access.load_local_accounts().get(pending.get("user", ""))
    if account is None or not account["totp"] or account["version"] != pending.get("v"):
        return None
    return pending["user"], account, safe_next(pending.get("next"))


@router.get("/codigo")
def totp_form(request: Request, error: str = ""):
    """Second step of a TOTP account: the 6-digit code of its authenticator app."""
    pending = pending_totp(request)
    if pending is None:
        request.session.pop("totp", None)
        return RedirectResponse("/auth/login?error=3", 302)
    token = request.session.get("login_csrf") or secrets.token_urlsafe(24)
    request.session["login_csrf"] = token
    message = {"1": "Código incorrecto. Escribe el que muestra ahora la aplicación.",
               "2": "Demasiados intentos fallidos. Espera unos minutos y vuelve a intentarlo.",
               "3": "El formulario ha caducado: vuelve a intentarlo."}.get(error, "")
    body = CODE.format(user=escape(pending[0]), csrf=escape(token),
                       error=f'<p class="error" role="alert">{escape(message)}</p>' if message else "")
    return HTMLResponse(PAGE.format(title="Código de verificación", message="", action=body).replace("<p></p>", ""),
                        401 if error == "1" else 429 if error == "2" else 200)


@router.post("/codigo")
async def totp_check(request: Request):
    fields = parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
    field = lambda name: (fields.get(name) or [""])[0]  # noqa: E731
    pending = pending_totp(request)
    if pending is None:
        request.session.pop("totp", None)
        return RedirectResponse("/auth/login?error=3", 303)
    name, account, next_path = pending
    expected = request.session.get("login_csrf", "")
    if not expected or not secrets.compare_digest(field("csrf").encode(), expected.encode()):
        return RedirectResponse("/auth/codigo?error=3", 303)
    address = request.client.host if request.client else "?"
    keys, now = [f"user:{name}", f"ip:{address}"], time.monotonic()
    if _blocked(keys, now):
        log.warning("Local sign-in blocked after repeated failures: %s from %s", name, address)
        return RedirectResponse("/auth/codigo?error=2", 303)
    step = identity.totp_step(account["totp"], field("codigo"))
    with _used_steps_lock:
        fresh = step is not None and step > _used_steps.get(name, -1)
        if fresh:
            _used_steps[name] = step
    if not fresh:  # wrong, expired, or already used once
        _failed(keys, now)
        log.warning("Local sign-in failed (TOTP code): %s from %s", name, address)
        return RedirectResponse("/auth/codigo?error=1", 303)
    return signed_in(request, account, name, address, next_path)


@router.get("/microsoft")
def microsoft(request: Request, next: str | None = None):
    if mode() != "entra":
        return RedirectResponse("/auth/login", 302)
    settings = EntraSettings.from_environment()
    try:
        scope = api_scope()
        flow = _client(settings).initiate_auth_code_flow([scope] if scope else [], redirect_uri=settings.redirect_uri)
    except Exception:  # first use downloads Entra's configuration: network or tenant problems
        log.exception("Sign-in: cannot start the Entra ID flow")
        return unavailable()
    request.session.clear()
    # The flow (state, nonce, PKCE verifier) goes in the signed session cookie, not on the server.
    request.session["flow"] = {key: value for key, value in flow.items() if key != "auth_uri"}
    request.session["next"] = safe_next(next)
    return RedirectResponse(flow["auth_uri"], 302)


@router.get("/callback")
def callback(request: Request):
    settings = EntraSettings.from_environment()
    flow = request.session.pop("flow", None)
    next_path = safe_next(request.session.pop("next", None))
    if not flow:  # expired or opened twice: start again
        return RedirectResponse("/auth/login", 302)
    # Checks state, nonce and the PKCE verifier, and redeems the code with the client secret.
    try:
        result = _client(settings).acquire_token_by_auth_code_flow(flow, dict(request.query_params))
    except ValueError as exc:  # state or nonce mismatch: a stale or forged response
        result = {"error": "invalid_response", "error_description": str(exc)}
    except Exception:
        log.exception("Sign-in: cannot redeem the code with Entra ID")
        return unavailable()
    claims = result.get("id_token_claims") or {}
    if "error" in result or claims.get("tid") != settings.tenant_id or claims.get("aud") != settings.client_id:
        log.warning("Sign-in rejected: %s %s", result.get("error", "unexpected tenant or audience"),
                    result.get("error_description", ""))
        return page("No se ha podido iniciar sesión",
                    "Microsoft no ha confirmado el inicio de sesión. Vuelve a intentarlo y, si se repite, "
                    "avisa a sistemas.", ("/auth/login", "Volver a intentarlo"), status=401)
    user = {
        "name": claims.get("name") or claims.get("preferred_username", ""),
        "email": claims.get("preferred_username", ""),
    }
    request.session.clear()
    request.session["user"] = user
    keep_api_token(request, result)
    log.info("Signed in: %s, roles %s", user["email"], ", ".join(access.roles_of(user["email"])) or "(none)")
    return RedirectResponse(next_path, 302)


@router.get("/logout")
def logout(request: Request):
    # Only the Sofibot session: the user stays signed in to Microsoft 365 (Outlook, Teams...).
    forget_api_token(request)
    request.session.clear()
    return page("Has cerrado la sesión", "Has salido del portal de informes.", ("/auth/login", "Volver a entrar"))


LOGIN = """<form method="post" action="/auth/local" class="login">{microsoft}{error}
<input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="next" value="{next}">
<label>Usuario<input name="usuario" autocomplete="username" required autofocus></label>
<label>Contraseña<input name="contrasena" type="password" autocomplete="current-password" required></label>
<button>Entrar</button></form>"""


def pending_activation(request: Request) -> tuple[str, dict, str, str] | None:
    """(name, account, next, new secret) after a right temporary password, while it can be finished."""
    data = request.session.get("activar")
    if not isinstance(data, dict) or time.time() - float(data.get("t") or 0) > ACTIVATION_MINUTES * 60:
        return None
    with _activation_lock:
        secret = _activation_secrets.get(data.get("k") or "", (None, 0.0))[0]
    account = access.load_local_accounts().get(data.get("user", ""))
    if (secret is None or account is None or not access.pending(account) or access.expired(account)
            or account["version"] != data.get("v")):
        return None
    return data["user"], account, safe_next(data.get("next")), secret


def qr_svg(uri: str) -> str:
    try:
        import segno
    except ImportError:
        return '<p class="note">(no se puede dibujar el QR: escribe la clave a mano en la aplicación)</p>'
    return segno.make(uri, error="m").svg_inline(scale=5, light="#fff", dark="#000")


@router.get("/activar")
def activation_form(request: Request, error: str = ""):
    """First sign-in of an account created with a temporary password: its password and its QR code."""
    found = pending_activation(request)
    if found is None:
        request.session.pop("activar", None)
        return RedirectResponse("/auth/login?error=3", 302)
    name, _, _, secret = found
    token = request.session.get("login_csrf") or secrets.token_urlsafe(24)
    request.session["login_csrf"] = token
    message = {"1": "Código incorrecto. Escribe el que muestra ahora la aplicación.",
               "2": "Demasiados intentos fallidos. Espera unos minutos y vuelve a intentarlo.",
               "3": "El formulario ha caducado: vuelve a intentarlo.",
               "5": f"La contraseña necesita {identity.MIN_PASSWORD} caracteres o más.",
               "6": "Las dos contraseñas no coinciden.",
               "7": "Elige una contraseña distinta de la temporal."}.get(error, "")
    key = " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
    body = ACTIVATE.format(user=escape(name), csrf=escape(token), qr=qr_svg(identity.totp_uri(name, secret)),
                           key=key, minimum=identity.MIN_PASSWORD,
                           error=f'<p class="error" role="alert">{escape(message)}</p>' if message else "")
    response = HTMLResponse(PAGE.format(title="Activa tu cuenta", message="", action=body).replace("<p></p>", ""),
                            400 if error in ("1", "5", "6", "7") else 429 if error == "2" else 200)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/activar")
async def activate(request: Request):
    fields = parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
    field = lambda name: (fields.get(name) or [""])[0]  # noqa: E731
    found = pending_activation(request)
    if found is None:
        request.session.pop("activar", None)
        return RedirectResponse("/auth/login?error=3", 303)
    name, account, next_path, secret = found
    expected = request.session.get("login_csrf", "")
    if not expected or not secrets.compare_digest(field("csrf").encode(), expected.encode()):
        return RedirectResponse("/auth/activar?error=3", 303)
    address = request.client.host if request.client else "?"
    keys, now = [f"user:{name}", f"ip:{address}"], time.monotonic()
    if _blocked(keys, now):
        log.warning("Local account activation blocked after repeated failures: %s from %s", name, address)
        return RedirectResponse("/auth/activar?error=2", 303)
    password = field("contrasena")
    if len(password) < identity.MIN_PASSWORD:
        return RedirectResponse("/auth/activar?error=5", 303)
    if field("repetir") != password:
        return RedirectResponse("/auth/activar?error=6", 303)
    if await run_in_threadpool(identity.password_matches, password, account["hash"]):
        return RedirectResponse("/auth/activar?error=7", 303)
    step = identity.totp_step(secret, field("codigo"))
    if step is None:
        _failed(keys, now)
        log.warning("Local account activation failed (TOTP code): %s from %s", name, address)
        return RedirectResponse("/auth/activar?error=1", 303)
    hashed = await run_in_threadpool(identity.hash_password, password)
    accounts = {n: dict(a) for n, a in access.read_totp_accounts().items()}
    if name not in accounts or accounts[name]["version"] != account["version"]:
        return RedirectResponse("/auth/login?error=3", 303)  # reset or removed meanwhile
    accounts[name].update(hash=hashed, totp=secret, activar_hasta=None, version=account["version"] + 1)
    access.save_totp_accounts(accounts)
    with _activation_lock:
        _activation_secrets.pop(request.session["activar"].get("k"), None)
    with _used_steps_lock:  # the code just typed cannot also sign in again
        _used_steps[name] = max(step, _used_steps.get(name, -1))
    log.info("Local account activated: %s from %s", name, address)
    return signed_in(request, accounts[name], name, address, next_path)


ACTIVATE = """<form method="post" action="/auth/activar" class="login">{error}
<p>Es la primera vez que entras como <b>{user}</b>. Para activar tu cuenta:</p>
<input type="hidden" name="csrf" value="{csrf}">
<h2>1. Tu contraseña</h2><p class="note">La temporal deja de valer. {minimum} caracteres o más: guárdala en tu gestor de
contraseñas.</p>
<label>Contraseña nueva<input name="contrasena" type="password" autocomplete="new-password" minlength="{minimum}" required></label>
<label>Repítela<input name="repetir" type="password" autocomplete="new-password" minlength="{minimum}" required></label>
<p><button type="button" class="sec" id="generar">Generar contraseña</button>
<button type="button" class="sec" id="copiar" hidden>Copiar</button></p>
<p class="note" id="generada" hidden>Contraseña generada: <code id="valor"></code><br><b>Guárdala ahora</b> en tu gestor de
contraseñas: Sofibot no la vuelve a mostrar.</p>
<script>
(function () {{
  // Made here, in the browser (crypto.getRandomValues): it never comes from the server.
  var chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_.", size = 20;
  var limit = 256 - 256 % chars.length, byte = new Uint8Array(1);
  var fields = document.querySelectorAll('input[name="contrasena"], input[name="repetir"]');
  var copy = document.getElementById("copiar"), value = document.getElementById("valor");
  document.getElementById("generar").addEventListener("click", function () {{
    var password = "";
    while (password.length < size) {{
      crypto.getRandomValues(byte);
      if (byte[0] < limit) password += chars[byte[0] % chars.length];  // no bias
    }}
    fields.forEach(function (field) {{ field.value = password; field.type = "text"; }});
    value.textContent = password;
    document.getElementById("generada").hidden = false;
    copy.hidden = false;
    copy.textContent = "Copiar";
  }});
  copy.addEventListener("click", function () {{
    var done = function () {{ copy.textContent = "Copiada"; }};
    if (navigator.clipboard && window.isSecureContext) {{
      navigator.clipboard.writeText(value.textContent).then(done);
    }} else {{
      var range = document.createRange();  // without HTTPS: select it, for Ctrl+C
      range.selectNodeContents(value);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
    }}
  }});
}})();
</script>
<h2>2. Tu móvil</h2><p class="note">Escanea este código QR con una aplicación de autenticación (Microsoft
Authenticator: <i>Agregar cuenta → Otra cuenta</i>). Solo tú lo ves.</p><div class="qr">{qr}</div>
<p class="note">O escríbela a mano (<i>Escribir código manualmente</i>): cuenta <b>{user}</b>, clave secreta
<code>{key}</code> (letras y números; basada en tiempo, 6 dígitos).</p>
<h2>3. Comprueba</h2>
<label>Código de 6 dígitos que muestra ahora la aplicación<input name="codigo" inputmode="numeric"
autocomplete="one-time-code" pattern="[0-9 ]{{6,7}}" maxlength="7" required></label>
<button>Activar y entrar</button> <a class="other" href="/auth/login">Cancelar</a></form>"""


CODE = """<form method="post" action="/auth/codigo" class="login">{error}
<p>Escribe el código de 6 dígitos que muestra la aplicación de autenticación para <b>{user}</b>.</p>
<input type="hidden" name="csrf" value="{csrf}">
<label>Código<input name="codigo" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{{6,7}}"
maxlength="7" required autofocus></label>
<button>Verificar</button> <a class="other" href="/auth/login">Volver</a></form>"""


def unavailable() -> HTMLResponse:
    return page("Inicio de sesión no disponible",
                "El portal no puede contactar con Microsoft en este momento. Vuelve a intentarlo en unos "
                "minutos y, si se repite, avisa a sistemas.", ("/auth/login", "Volver a intentarlo"), status=503)


def page(title: str, message: str, link: tuple[str, str] | None = None, status: int = 200) -> HTMLResponse:
    action = f'<a href="{escape(link[0])}">{escape(link[1])}</a>' if link else ""
    return HTMLResponse(PAGE.format(title=escape(title), message=escape(message), action=action), status)


PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · Sofibot</title><style>
body{{margin:0;background:#f4f7fb;color:#2C3968;font:16px/1.5 Roboto,Arial,sans-serif}}
header{{background:#2C3968;color:#fff;padding:18px 24px;font-size:22px;font-weight:500}}
main{{max-width:560px;margin:48px auto;padding:28px;background:#fff;border:1px solid #dfe5ee;border-top:4px solid #D16B1B;border-radius:14px}}
h1{{margin:0 0 8px;font-size:21px}}a{{display:inline-block;margin-top:12px;padding:8px 14px;border-radius:8px;background:#2C3968;color:#fff;text-decoration:none;font-weight:500}}
a:focus-visible,input:focus-visible,button:focus-visible{{outline:3px solid #D16B1B;outline-offset:2px}}
.login label{{display:block;margin:10px 0;font-size:14px}}.login input{{display:block;width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;font:inherit;border:1px solid #dfe5ee;border-radius:8px}}
.login button{{margin-top:8px;padding:9px 16px;border:0;border-radius:8px;background:#2C3968;color:#fff;font:inherit;font-weight:500;cursor:pointer}}
.login button.sec{{background:#fff;color:#2C3968;border:1px solid #2C3968;padding:6px 12px}}
.login .ms{{display:block;text-align:center;margin:0}}.or{{text-align:center;color:#566173;font-size:14px;margin:16px 0 4px}}
.error{{color:#b3261e;font-weight:500}}.note{{color:#566173;font-size:14px}}
.login h2{{font-size:17px;margin:18px 0 4px}}.qr{{display:inline-block;background:#fff;padding:10px;border:1px solid #dfe5ee;border-radius:8px}}.login .other{{background:none;color:#2C3968;margin-left:8px}}
</style></head><body><header>Sofibot · Informes</header><main><h1>{title}</h1><p>{message}</p>{action}</main></body></html>"""

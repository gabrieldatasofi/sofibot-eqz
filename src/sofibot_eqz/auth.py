"""Sign-in to the portal, chosen with SOFIBOT_AUTH:

- none: open portal (only for a server nobody else can reach);
- basic: one shared user and password (SOFIBOT_VIEWER_USER / SOFIBOT_VIEWER_PASSWORD);
- entra: each person signs in with their Microsoft Entra ID account (OpenID Connect,
  authorization code flow with PKCE, through Microsoft's MSAL library). Entra ID only says
  who they are; their roles, and so what they see, come from acceso/usuarios.json (access.py).

Without SOFIBOT_AUTH: basic if SOFIBOT_VIEWER_PASSWORD is set, none otherwise.

With Entra ID and the query service configured (SOFIBOT_QUERY_URL), sign-in also obtains an
access token for Sofibot's own API (scope SOFIBOT_API_SCOPE), so that the portal's query page
can forward a user's query to the query service as that user. The token is kept in this
process's memory, keyed by a random id in the session cookie; never in the cookie itself.
"""
from dataclasses import dataclass
import functools
from html import escape
import logging
import os
import secrets
import threading
import time
import warnings

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import access

MODES = ("none", "basic", "entra")
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
    """The signed-in user's token for Sofibot's API, or None (not requested, expired, restarted)."""
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


def check_settings(env=os.environ) -> str:
    """Fail at start-up, with the variable to fix, rather than on the first sign-in."""
    current = mode(env)
    if current == "basic" and not env.get("SOFIBOT_VIEWER_PASSWORD"):
        raise RuntimeError("SOFIBOT_AUTH=basic needs SOFIBOT_VIEWER_PASSWORD")
    if current == "entra":
        EntraSettings.from_environment(env)
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
    """The signed-in Entra user, or None when the portal has no per-user sign-in."""
    if mode() != "entra":
        return None
    # The sign-in middleware only lets signed-in users through; an empty user sees nothing.
    user = dict(request.session.get("user") or {"name": "", "email": ""})
    # Roles come from acceso/usuarios.json on every request, never from Entra: a change applies at once.
    user["roles"] = list(access.roles_of(user.get("email", "")))
    return user


def safe_next(value: str | None) -> str:
    """Only paths on this site: '//host' or '/\\host' would send the user elsewhere."""
    if not value or not value.startswith("/") or value.startswith(("//", "/\\")) or any(c < " " for c in value):
        return "/explore"
    return value


@router.get("/login")
def login(request: Request, next: str | None = None):
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
a:focus-visible{{outline:3px solid #D16B1B;outline-offset:2px}}
</style></head><body><header>Sofibot · Informes</header><main><h1>{title}</h1><p>{message}</p>{action}</main></body></html>"""

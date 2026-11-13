"""Shared by the two Sofibot MCP servers: sign in with Microsoft (Entra ID) and call Sofibot.

The first call opens the browser to sign in with the user's company account; the session is
kept in ~/.sofibot/msal-cache.json (only on this computer), so later calls are silent. Each
API then knows who is calling and applies that person's roles and tables.

Settings (environment): SOFIBOT_URL, SOFIBOT_ENTRA_TENANT_ID, SOFIBOT_ENTRA_CLIENT_ID,
optionally SOFIBOT_ENTRA_SCOPE, SOFIBOT_CA_BUNDLE (company CA) and SOFIBOT_AI (claude, codex...).
For tests only, SOFIBOT_API_TOKEN (the server's shared token) replaces the sign-in.
"""
import os
from pathlib import Path
import threading

import httpx

CACHE = Path(os.environ.get("SOFIBOT_TOKEN_CACHE", Path.home() / ".sofibot" / "msal-cache.json"))
_app = None
_lock = threading.Lock()


class SignInError(Exception):
    pass


def _entra_token() -> str:
    import msal

    global _app
    tenant, client = os.environ.get("SOFIBOT_ENTRA_TENANT_ID", ""), os.environ.get("SOFIBOT_ENTRA_CLIENT_ID", "")
    if not tenant or not client:
        raise SignInError("Configure SOFIBOT_ENTRA_TENANT_ID and SOFIBOT_ENTRA_CLIENT_ID (Sofibot, page 'Conectar tu IA')")
    scopes = [os.environ.get("SOFIBOT_ENTRA_SCOPE") or f"api://{client}/access_as_user"]
    with _lock:
        if _app is None:
            cache = msal.SerializableTokenCache()
            if CACHE.is_file():
                cache.deserialize(CACHE.read_text(encoding="utf-8"))
            _app = msal.PublicClientApplication(client, authority=f"https://login.microsoftonline.com/{tenant}",
                                                token_cache=cache)
        accounts = _app.get_accounts()
        result = _app.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
        if not result:
            result = _app.acquire_token_interactive(scopes, prompt="select_account")
        if "access_token" not in result:
            raise SignInError(f"Microsoft sign-in failed: {result.get('error_description') or result.get('error')}")
        if _app.token_cache.has_state_changed:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(_app.token_cache.serialize(), encoding="utf-8")
            try:
                CACHE.chmod(0o600)
            except OSError:
                pass
    return result["access_token"]


def call(method: str, path: str, payload: dict | None = None, channel: str = "mcp") -> dict:
    """Call Sofibot (path from the site root, e.g. /api/code/schema). Errors come back as {"error": ...}."""
    base = os.environ.get("SOFIBOT_URL", "").rstrip("/")
    if not base:
        return {"error": "Configure SOFIBOT_URL for this MCP server"}
    try:
        shared = os.environ.get("SOFIBOT_API_TOKEN", "")
        authorization = f"Bearer {shared or _entra_token()}"
    except SignInError as exc:
        return {"error": str(exc)}
    try:
        with httpx.Client(timeout=120, follow_redirects=False,
                          verify=os.environ.get("SOFIBOT_CA_BUNDLE") or True) as client:
            response = client.request(method, f"{base}{path}", json=payload,
                                      headers={"Authorization": authorization, "X-Sofibot-Channel": channel})
    except httpx.HTTPError as exc:
        return {"error": f"Sofibot is not reachable: {exc}"}
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        detail = body.get("detail") if isinstance(body, dict) else None
        return {"error": detail or f"HTTP {response.status_code}"}
    return body

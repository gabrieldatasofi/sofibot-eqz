"""Who is calling, the same way for both functionalities (docs/11-consultas.md, docs/10-api-informes.md).

People sign in with Microsoft Entra ID or, with a local account (acceso/cuentas-locales.json),
with a user name and password, plus a TOTP code for the accounts in acceso/cuentas-totp.json. The portal keeps the user in its session (auth.py); the APIs
receive a token (`Authorization: Bearer <token>`) that a client, such as the Sofibot MCP
server, sends for the user:

- an Entra access token, obtained by signing the user in. Checked here: signed by Entra for
  this tenant, issued for this application, for a user (a delegated token with `scp`, not an
  application's own token) and not expired;
- for a local account, a token issued by Sofibot itself (page "Conectar tu IA"), signed with
  SOFIBOT_LOCAL_SECRET, which the portal and the query service share. It is only valid while
  the account exists and its password has not changed since (the account's "version").

Entra ID only says who the user is. What they may do is decided by Sofibot, the same way for
both functionalities (access.py): acceso/usuarios.json gives each e-mail its roles, the
function roles below (one per functionality) and data roles, and acceso/permisos.json gives
each data role its Gold tables. Roles in the token, if the Entra app still has any, are ignored.
"""
import base64
from dataclasses import dataclass, field
import functools
import hashlib
import os
import secrets
import time

ROLE_AUTHOR = "Sofibot.Autor"        # functionality 1: read the schema, write report drafts
ROLE_REVIEWER = "Sofibot.Revisor"    # functionality 1: preview, publish or reject drafts
ROLE_QUERY = "Sofibot.Consultas"     # functionality 2: query data
ROLE_ADMIN = "Sofibot.Admin"         # administration page: status, users, permissions, documentation
FUNCTION_ROLES = (ROLE_AUTHOR, ROLE_REVIEWER, ROLE_QUERY, ROLE_ADMIN)
ALL_TABLES = None                    # tables() for a caller restricted to no table set


def full_access(roles) -> bool:
    """Every function role and "*" (every Gold table, whatever the client's tables are): a local
    account such as supersofi, shown as "acceso total" in the administration page and the CLI."""
    return "*" in roles and all(role in roles for role in FUNCTION_ROLES)


class IdentityError(Exception):
    """The token is missing, invalid or not for this application. The message is safe to return."""


@dataclass(frozen=True)
class Identity:
    email: str
    name: str = ""
    roles: tuple[str, ...] = field(default_factory=tuple)
    via: str = "entra"               # entra | local (local account) | token (shared token, tests only) | cli

    @property
    def per_user(self) -> bool:
        """A person with roles (Entra ID or local account), not the shared test token or the CLI."""
        return self.via in ("entra", "local")

    def has(self, role: str) -> bool:
        return not self.per_user or role in self.roles

    def tables(self, permissions: dict[str, set[str]]) -> set[str] | None:
        """Gold tables this user may touch (lower case); None = every table (shared token, CLI)."""
        from .access import ALL, granted

        if not self.per_user:
            return ALL_TABLES
        allowed = granted(self.roles, permissions)
        return ALL_TABLES if ALL in allowed else allowed


@dataclass(frozen=True)
class EntraApi:
    tenant_id: str
    client_id: str

    @classmethod
    def from_environment(cls, env=os.environ) -> "EntraApi":
        tenant, client = env.get("ENTRA_TENANT_ID", "").strip(), env.get("ENTRA_CLIENT_ID", "").strip()
        if not tenant or not client:
            raise IdentityError("ENTRA_TENANT_ID and ENTRA_CLIENT_ID are not configured")
        return cls(tenant, client)

    @property
    def audiences(self) -> list[str]:
        return [self.client_id, f"api://{self.client_id}"]

    @property
    def issuers(self) -> list[str]:
        return [f"https://login.microsoftonline.com/{self.tenant_id}/v2.0", f"https://sts.windows.net/{self.tenant_id}/"]


@functools.cache
def _jwks(tenant_id: str):
    import jwt

    return jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
                           cache_keys=True, lifespan=3600, timeout=10)


def _signing_key(token: str, settings: EntraApi):
    """The Entra public key that signed the token (downloaded and cached)."""
    return _jwks(settings.tenant_id).get_signing_key_from_jwt(token).key


def from_bearer(authorization: str, env=os.environ) -> Identity:
    """Identity from an `Authorization: Bearer <token>` header (Entra or Sofibot's own), or IdentityError."""
    import jwt

    if not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise IdentityError("Sign-in required: send a Microsoft Entra ID access token or a Sofibot token")
    token = authorization[7:].strip()
    try:
        algorithm = jwt.get_unverified_header(token).get("alg")
    except jwt.InvalidTokenError as exc:
        raise IdentityError(f"Invalid token: {exc}") from exc
    # Only chooses which check runs: each one accepts its own algorithm alone (HS256 or RS256).
    if algorithm == LOCAL_ALGORITHM:
        return from_local_token(token, env)
    settings = EntraApi.from_environment(env)
    try:
        claims = jwt.decode(token, _signing_key(token, settings), algorithms=["RS256"],
                            audience=settings.audiences, issuer=settings.issuers, leeway=60,
                            options={"require": ["exp", "iat", "aud", "iss", "tid"]})
    except jwt.PyJWKClientError as exc:
        raise IdentityError("Cannot check the token: Entra ID keys unavailable") from exc
    except jwt.InvalidTokenError as exc:
        raise IdentityError(f"Invalid token: {exc}") from exc
    if claims.get("tid") != settings.tenant_id:
        raise IdentityError("Invalid token: another tenant")
    if not claims.get("scp"):
        raise IdentityError("Invalid token: it must be a user's token (delegated), not an application's")
    email = claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name") or ""
    if not email:
        raise IdentityError("Invalid token: no user name")
    from .access import roles_of

    return Identity(email=email, name=claims.get("name", ""), roles=roles_of(email))


def from_session(user: dict) -> Identity:
    """The portal's signed-in user (auth.current_user, which already looked up the roles)."""
    return Identity(email=user.get("email", ""), name=user.get("name", ""), roles=tuple(user.get("roles", ())),
                    via="local" if user.get("local") else "entra")


# --- Local accounts: passwords and Sofibot's own tokens -----------------------------------

# scrypt (memory-hard, in Python's standard library). The parameters are stored with each
# hash, so they can be raised later without invalidating the existing passwords.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
MIN_PASSWORD = 12
LOCAL_ALGORITHM, LOCAL_ISSUER, LOCAL_AUDIENCE = "HS256", "sofibot", "sofibot-api"
_dummy_hash: list[str] = []


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"The password needs {MIN_PASSWORD} characters or more")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def password_matches(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r),
                                p=int(p), maxmem=128 * 1024 * 1024, dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(actual, expected)


def local_sign_in(name: str, password: str) -> dict | None:
    """The local account (with its "usuario") if the password is right, else None."""
    from .access import load_local_accounts

    name = (name or "").strip().casefold()
    account = load_local_accounts().get(name)
    if account is None:
        # Spend the same time as a real check, so that timing does not tell which names exist.
        if not _dummy_hash:
            _dummy_hash.append(hash_password(secrets.token_urlsafe(16)))
        password_matches(password, _dummy_hash[0])
        return None
    if not password_matches(password, account["hash"]):
        return None
    return {**account, "usuario": name}


# --- TOTP (RFC 6238): the code of an authenticator app, for accounts in cuentas-totp.json -----
TOTP_DIGITS, TOTP_PERIOD, TOTP_ISSUER = 6, 30, "Sofibot"


def new_totp_secret() -> str:
    """160 random bits in base32 without padding, as authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_code(secret: str, step: int) -> str:
    """The code for one 30-second step (HMAC-SHA1, 6 digits: what every authenticator app uses)."""
    import hmac

    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, step.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return str(value % 10 ** TOTP_DIGITS).zfill(TOTP_DIGITS)


def totp_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The step whose code this is (now, or one step either side for clock drift), or None.

    The caller rejects a step it has already accepted, so that a code works only once."""
    code = "".join((code or "").split())
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    current = int((time.time() if now is None else now) // TOTP_PERIOD)
    found = None
    for step in (current - 1, current, current + 1):  # check all three: same time for any code
        if secrets.compare_digest(totp_code(secret, step), code):
            found = step
    return found


def totp_uri(name: str, secret: str) -> str:
    """otpauth:// address for the app's QR code: issuer Sofibot, the account's user name."""
    from urllib.parse import quote

    return (f"otpauth://totp/{quote(TOTP_ISSUER)}:{quote(name)}?secret={secret}&issuer={quote(TOTP_ISSUER)}"
            f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}")


def local_secret(env=os.environ) -> str | None:
    """SOFIBOT_LOCAL_SECRET when usable: 32 characters or more, different from the other tokens."""
    value = env.get("SOFIBOT_LOCAL_SECRET", "").strip()
    others = {env.get("SOFIBOT_ADMIN_TOKEN", "").strip(), env.get("SOFIBOT_API_TOKEN", "").strip()}
    return value if len(value) >= 32 and value not in others else None


def token_days(env=os.environ) -> int:
    """How long a token from the page 'Conectar tu IA' lasts (SOFIBOT_LOCAL_TOKEN_DAYS, 1 to 365)."""
    try:
        days = int(env.get("SOFIBOT_LOCAL_TOKEN_DAYS", "") or 30)
    except ValueError:
        days = 30
    return max(1, min(365, days))


def issue_token(name: str, account: dict, minutes: int, env=os.environ) -> str:
    """A token for a local account, for the MCP servers and the query service."""
    import jwt

    secret = local_secret(env)
    if secret is None:
        raise IdentityError("SOFIBOT_LOCAL_SECRET is not configured (32 characters or more)")
    now = int(time.time())
    claims = {"iss": LOCAL_ISSUER, "aud": LOCAL_AUDIENCE, "sub": name, "name": account.get("nombre", name),
              "ver": account["version"], "iat": now, "exp": now + minutes * 60}
    return jwt.encode(claims, secret, algorithm=LOCAL_ALGORITHM)


def from_local_token(token: str, env=os.environ) -> Identity:
    """Identity from a token issued by issue_token(), or IdentityError."""
    import jwt

    from .access import load_local_accounts

    secret = local_secret(env)
    if secret is None:
        raise IdentityError("Sofibot tokens are not accepted here (SOFIBOT_LOCAL_SECRET is not configured)")
    try:
        claims = jwt.decode(token, secret, algorithms=[LOCAL_ALGORITHM], audience=LOCAL_AUDIENCE,
                            issuer=LOCAL_ISSUER, leeway=60, options={"require": ["exp", "iat", "sub", "ver"]})
    except jwt.InvalidTokenError as exc:
        raise IdentityError(f"Invalid token: {exc}") from exc
    account = load_local_accounts().get(claims["sub"])
    if account is None or account.get("activar_hasta") is not None or account["version"] != claims["ver"]:
        raise IdentityError("Invalid token: the account no longer exists or its password has changed; "
                            "create a new token in Sofibot, page 'Conectar tu IA'")
    return Identity(email=claims["sub"], name=account["nombre"], roles=account["roles"], via="local")

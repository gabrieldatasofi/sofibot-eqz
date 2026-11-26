"""Who is calling, the same way for both functionalities (docs/11-consultas.md, docs/10-api-informes.md).

Everyone signs in with Microsoft Entra ID. The portal keeps the user in its session
(auth.py); the APIs receive an Entra access token (`Authorization: Bearer <token>`) that a
client, such as the Sofibot MCP server, obtained by signing the user in. This module checks
that token: signed by Entra for this tenant, issued for this application, for a user (a
delegated token with `scp`, not an application's own token) and not expired.

Entra ID only says who the user is. What they may do is decided by Sofibot, the same way for
both functionalities (access.py): acceso/usuarios.json gives each e-mail its roles, the
function roles below (one per functionality) and data roles, and acceso/permisos.json gives
each data role its Gold tables. Roles in the token, if the Entra app still has any, are ignored.
"""
from dataclasses import dataclass, field
import functools
import os

ROLE_AUTHOR = "Sofibot.Autor"        # functionality 1: read the schema, write report drafts
ROLE_REVIEWER = "Sofibot.Revisor"    # functionality 1: preview, publish or reject drafts
ROLE_QUERY = "Sofibot.Consultas"     # functionality 2: query data
ROLE_ADMIN = "Sofibot.Admin"         # administration page: status, users, permissions, documentation
FUNCTION_ROLES = (ROLE_AUTHOR, ROLE_REVIEWER, ROLE_QUERY, ROLE_ADMIN)
ALL_TABLES = None                    # tables() for a caller restricted to no table set


class IdentityError(Exception):
    """The token is missing, invalid or not for this application. The message is safe to return."""


@dataclass(frozen=True)
class Identity:
    email: str
    name: str = ""
    roles: tuple[str, ...] = field(default_factory=tuple)
    via: str = "entra"               # entra | token (shared token, tests only) | cli

    def has(self, role: str) -> bool:
        return self.via != "entra" or role in self.roles

    def tables(self, permissions: dict[str, set[str]]) -> set[str] | None:
        """Gold tables this user may touch (lower case); None = every table (shared token, CLI)."""
        from .access import ALL, granted

        if self.via != "entra":
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
    """Identity from an `Authorization: Bearer <Entra access token>` header, or IdentityError."""
    import jwt

    if not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise IdentityError("Sign-in required: send a Microsoft Entra ID access token")
    token = authorization[7:].strip()
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
    return Identity(email=user.get("email", ""), name=user.get("name", ""), roles=tuple(user.get("roles", ())))

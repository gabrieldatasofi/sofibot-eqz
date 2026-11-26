"""Who may do what with per-user sign-in (docs/09-inicio-sesion-entra.md).

Entra ID only signs users in: it says who the user is (their e-mail), nothing else. Sofibot
decides what they may do, with the files in the acceso/ folder:

- usuarios.json: each user's roles, by e-mail. Function roles (Sofibot.Autor, ...) open each
  functionality; data roles (any other name) give Gold tables.
- permisos.json: each data role's Gold tables ("*" = all).
- cuentas-locales.json: accounts that sign in with a user name and password instead of
  Entra ID (the emergency administrator, or every user where there is no Entra ID). Only
  the password's hash is kept; each account carries its own roles, where "*" means every
  Gold table (identity.py checks the passwords and Sofibot's own tokens).

A report is visible when the user's roles, together, cover every table the report reads (its
report.json "tables"): a report is built in advance for everyone, so it cannot show only part
of itself. Both files are read on every request, so a change applies without restarting and
without signing in again. Installations from before acceso/ keep reports/permisos.json until
the permissions are first saved from the administration page.
"""
from datetime import datetime
import json
import logging
import os
import re

from . import config

ALL = "*"
TABLE = re.compile(r"\w+\.\w+")
ROLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
EMAIL = re.compile(r"[^@\s\"<>]+@[^@\s\"<>]+")
# Local account names have no "@", so they can never be mistaken for an Entra ID user.
USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")
log = logging.getLogger("sofibot")


class PermissionsError(Exception):
    pass


# --- Files --------------------------------------------------------------------------------

def users_file():
    return config.ACCESS_DIR / "usuarios.json"


def legacy_permissions_file():
    return config.REPORTS_DIR / "permisos.json"


def permissions_file():
    """acceso/permisos.json; reports/permisos.json only while an older installation has no new file."""
    path = config.ACCESS_DIR / "permisos.json"
    legacy = legacy_permissions_file()
    return legacy if not path.is_file() and legacy.is_file() else path


def save(path, data: dict, check) -> None:
    """Write a JSON file, keeping the previous one in acceso/.copias/; restore it if check() fails."""
    previous = path.read_text(encoding="utf-8") if path.is_file() else None
    if previous is not None:
        backup = config.ACCESS_DIR / ".copias" / f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(previous, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        check()
    except PermissionsError:
        if previous is None:
            path.unlink()
        else:
            path.write_text(previous, encoding="utf-8")
        raise


def _json(path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PermissionsError(f"{path} does not exist") from exc
    except (OSError, ValueError) as exc:
        raise PermissionsError(f"{path}: {exc}") from exc


# --- Users: e-mail -> roles ---------------------------------------------------------------

def read_users() -> dict[str, tuple[str, ...]]:
    """E-mail (lower case) -> roles. Raises PermissionsError if missing or malformed."""
    path = users_file()
    data = _json(path)
    users = data.get("usuarios") if isinstance(data, dict) else None
    if not isinstance(users, dict):
        raise PermissionsError(f'{path}: expected {{"usuarios": {{"<e-mail>": ["<role>", ...]}}}}')
    result = {}
    for email, roles in users.items():
        key = email.strip().casefold()
        if not EMAIL.fullmatch(key):
            raise PermissionsError(f'{path}: "{email}" is not an e-mail address')
        if key in result:
            raise PermissionsError(f'{path}: "{email}" appears twice')
        if not isinstance(roles, list) or not all(isinstance(r, str) and ROLE_NAME.fullmatch(r) for r in roles):
            raise PermissionsError(f'{path}: "{email}" must map to a list of role names')
        result[key] = tuple(sorted(set(roles)))
    return result


def load_users() -> dict[str, tuple[str, ...]]:
    """Like read_users(), but a missing or broken file gives nobody any role instead of failing."""
    try:
        return read_users()
    except PermissionsError as exc:
        log.warning("Users: %s. Signed-in users have no roles until it is fixed.", exc)
        return {}


def roles_of(email: str) -> tuple[str, ...]:
    """The roles Sofibot gives this signed-in user (none if they are not in usuarios.json)."""
    return load_users().get((email or "").strip().casefold(), ())


def save_users(users: dict[str, list[str]]) -> None:
    save(users_file(), {"usuarios": {email: sorted(set(roles)) for email, roles in sorted(users.items())}}, read_users)


# --- Local accounts: user name -> password hash and roles -------------------------------

def local_accounts_file():
    return config.ACCESS_DIR / "cuentas-locales.json"


def read_local_accounts() -> dict[str, dict]:
    """Name -> {"nombre", "hash", "version", "roles"}. Missing file: no accounts. Malformed: PermissionsError."""
    path = local_accounts_file()
    if not path.is_file():
        return {}
    data = _json(path)
    accounts = data.get("cuentas") if isinstance(data, dict) else None
    if not isinstance(accounts, dict):
        raise PermissionsError(f'{path}: expected {{"cuentas": {{"<user>": {{"hash": ..., "roles": [...]}}}}}}')
    result = {}
    for name, account in accounts.items():
        if not USERNAME.fullmatch(name):
            raise PermissionsError(f'{path}: "{name}" is not a valid user name (lower case, no "@")')
        roles = account.get("roles") if isinstance(account, dict) else None
        if (not isinstance(account.get("hash"), str) or not isinstance(account.get("version"), int)
                or not isinstance(roles, list)
                or not all(isinstance(r, str) and (r == ALL or ROLE_NAME.fullmatch(r)) for r in roles)):
            raise PermissionsError(f'{path}: "{name}" needs "hash", a whole "version" and a list of "roles"')
        result[name] = {"nombre": str(account.get("nombre") or name), "hash": account["hash"],
                        "version": account["version"], "roles": tuple(sorted(set(roles)))}
    return result


def load_local_accounts() -> dict[str, dict]:
    """Like read_local_accounts(), but a broken file lets no local account in instead of failing."""
    try:
        return read_local_accounts()
    except PermissionsError as exc:
        log.warning("Local accounts: %s. No local account can sign in until it is fixed.", exc)
        return {}


def save_local_accounts(accounts: dict[str, dict]) -> None:
    data = {name: {"nombre": a["nombre"], "hash": a["hash"], "version": a["version"], "roles": sorted(set(a["roles"]))}
            for name, a in sorted(accounts.items())}
    save(local_accounts_file(), {"cuentas": data}, read_local_accounts)


# --- Permissions: data role -> Gold tables ------------------------------------------------

def read() -> dict[str, set[str]]:
    """Role -> Gold tables (lower case) or {"*"}. Raises PermissionsError if missing or malformed."""
    path = permissions_file()
    data = _json(path)
    roles = data.get("roles") if isinstance(data, dict) else None
    if not isinstance(roles, dict):
        raise PermissionsError(f'{path}: expected {{"roles": {{"<role>": ["gold.<table>", ...]}}}}')
    schema = os.environ.get("SQLSERVER_GOLD_SCHEMA", "gold").casefold()
    permissions = {}
    for role, tables in roles.items():
        if not isinstance(tables, list) or not all(
                isinstance(t, str) and (t == ALL or (TABLE.fullmatch(t) and t.split(".")[0].casefold() == schema))
                for t in tables):
            raise PermissionsError(f'{path}: role "{role}" must map to a list of tables like "{schema}.ventas" or "*"')
        permissions[role] = {table.casefold() for table in tables}
    return permissions


def load() -> dict[str, set[str]]:
    """Like read(), but a broken file denies everything instead of failing the request."""
    try:
        return read()
    except PermissionsError as exc:
        log.warning("Permissions: %s. Signed-in users see no reports until it is fixed.", exc)
        return {}


def save_permissions(roles: dict[str, list[str]]) -> None:
    """Always into acceso/: from then on an older reports/permisos.json is no longer read."""
    config.ACCESS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.ACCESS_DIR / "permisos.json"
    save(path, {"roles": roles}, read)


def granted(roles, permissions: dict[str, set[str]]) -> set[str]:
    """Union of the tables of every role the user has. "*" among the roles (only a local
    account can have it: usuarios.json rejects it) is every table."""
    if ALL in roles:
        return {ALL}
    return set().union(*(permissions.get(role, set()) for role in roles))


def covers(tables: set[str], report_tables) -> bool:
    """A report whose tables are unknown is only visible with "*"."""
    report_tables = {table.casefold() for table in report_tables}
    return ALL in tables or (bool(report_tables) and report_tables <= tables)


def visible(user: dict | None, report_tables, permissions: dict[str, set[str]] | None = None) -> bool:
    """None = no per-user sign-in (open portal or shared password): every report is visible."""
    if user is None:
        return True
    permissions = load() if permissions is None else permissions
    return covers(granted(user.get("roles", ()), permissions), report_tables)

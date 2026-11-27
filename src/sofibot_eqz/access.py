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
- cuentas-totp.json: the same, plus a code from an authenticator app (TOTP). It keeps each
  account's TOTP secret, so it never goes in git or in an installation package.
SOFIBOT_LOCAL_ACCOUNTS chooses which of the two kinds may sign in.

A report is visible when the user's roles, together, cover every table the report reads (its
report.json "tables"): a report is built in advance for everyone, so it cannot show only part
of itself. Both files are read on every request, so a change applies without restarting and
without signing in again. Installations from before acceso/ keep reports/permisos.json until
the permissions are first saved from the administration page.
"""
from datetime import datetime, timedelta, timezone
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
# Two kinds, in two files: cuentas-locales.json (user name and password) and cuentas-totp.json
# (user name, password and a TOTP code from an authenticator app). The second keeps each
# account's TOTP secret, which, unlike a hash, is enough to make codes: it never goes in git.
PASSWORD, TOTP = "password", "totp"
KINDS = (PASSWORD, TOTP)
BASE32 = re.compile(r"[A-Z2-7]{16,128}")


def local_accounts_file():
    return config.ACCESS_DIR / "cuentas-locales.json"


def totp_accounts_file():
    return config.ACCESS_DIR / "cuentas-totp.json"


def accounts_file(kind: str):
    return totp_accounts_file() if kind == TOTP else local_accounts_file()


def enabled_kinds(env=os.environ) -> tuple[str, ...]:
    """SOFIBOT_LOCAL_ACCOUNTS: which kinds of local account may sign in ("password,totp" by default)."""
    value = env.get("SOFIBOT_LOCAL_ACCOUNTS", "").replace(" ", "").lower()
    if not value:
        return KINDS
    kinds = tuple(dict.fromkeys(value.split(",")))
    if bad := [k for k in kinds if k not in KINDS]:
        raise PermissionsError(f"SOFIBOT_LOCAL_ACCOUNTS: unknown {', '.join(bad)} (use password, totp or both)")
    return kinds


def activation_days(env=os.environ) -> int:
    """SOFIBOT_LOCAL_ACTIVATION_DAYS: days a new TOTP account's temporary password lasts (1 to 30)."""
    try:
        days = int(env.get("SOFIBOT_LOCAL_ACTIVATION_DAYS", "") or 7)
    except ValueError:
        days = 7
    return max(1, min(30, days))


def activation_deadline(env=os.environ) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(days=activation_days(env))).replace(microsecond=0)


def pending(account: dict) -> bool:
    """A TOTP account created with a temporary password that its owner has not activated yet."""
    return account.get("activar_hasta") is not None


def expired(account: dict) -> bool:
    return pending(account) and account["activar_hasta"] <= datetime.now(timezone.utc)


def read_accounts(kind: str) -> dict[str, dict]:
    """Name -> {"nombre", "hash", "version", "roles", "tipo", "totp", "activar_hasta"} of one kind.

    "totp" is the account's TOTP secret, None for a password-only account and for a TOTP account
    still to be activated: then "activar_hasta" says until when its temporary password works (its
    owner chooses a password and scans the QR code at the first sign-in). Missing file: no
    accounts. Malformed: PermissionsError."""
    path = accounts_file(kind)
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
        account = account if isinstance(account, dict) else {}
        roles = account.get("roles")
        if (not isinstance(account.get("hash"), str) or not isinstance(account.get("version"), int)
                or not isinstance(roles, list)
                or not all(isinstance(r, str) and (r == ALL or ROLE_NAME.fullmatch(r)) for r in roles)):
            raise PermissionsError(f'{path}: "{name}" needs "hash", a whole "version" and a list of "roles"')
        secret, until = account.get("totp"), None
        if kind == TOTP and secret is None and "activar_hasta" in account:
            try:
                until = datetime.fromisoformat(str(account["activar_hasta"]))
            except ValueError:
                until = None
            if until is None or until.tzinfo is None:
                raise PermissionsError(f'{path}: "{name}": "activar_hasta" must be a date with its time zone')
        elif kind == TOTP and not (isinstance(secret, str) and BASE32.fullmatch(secret)):
            raise PermissionsError(f'{path}: "{name}" needs its "totp" secret (create it with  sofibot local-account totp)')
        result[name] = {"nombre": str(account.get("nombre") or name), "hash": account["hash"],
                        "version": account["version"], "roles": tuple(sorted(set(roles))), "tipo": kind,
                        "totp": secret if kind == TOTP else None, "activar_hasta": until}
    return result


def read_local_accounts() -> dict[str, dict]:
    """The password-only accounts (cuentas-locales.json)."""
    return read_accounts(PASSWORD)


def read_totp_accounts() -> dict[str, dict]:
    """The accounts with a TOTP code (cuentas-totp.json)."""
    return read_accounts(TOTP)


def load_local_accounts(env=os.environ) -> dict[str, dict]:
    """Every local account that may sign in now: of the kinds SOFIBOT_LOCAL_ACCOUNTS enables.

    A broken file lets none of its accounts in instead of failing; a name in both files signs
    in with neither (it is ambiguous which one is meant)."""
    try:
        kinds = enabled_kinds(env)
    except PermissionsError as exc:
        log.warning("Local accounts: %s. No local account can sign in until it is fixed.", exc)
        return {}
    found: list[dict[str, dict]] = []
    for kind in kinds:
        try:
            found.append(read_accounts(kind))
        except PermissionsError as exc:
            log.warning("Local accounts: %s. None of its accounts can sign in until it is fixed.", exc)
    result: dict[str, dict] = {}
    for accounts in found:
        result.update(accounts)
    if len(found) == 2 and (both := set(found[0]) & set(found[1])):
        log.warning("Local accounts in both files cannot sign in: %s", ", ".join(sorted(both)))
        for name in both:
            del result[name]
    return result


def save_accounts(kind: str, accounts: dict[str, dict]) -> None:
    data = {}
    for name, a in sorted(accounts.items()):
        data[name] = {"nombre": a["nombre"], "hash": a["hash"], "version": a["version"], "roles": sorted(set(a["roles"]))}
        if kind == TOTP:
            data[name]["totp"] = a.get("totp")
            if a.get("totp") is None:
                data[name]["activar_hasta"] = a["activar_hasta"].isoformat()
    save(accounts_file(kind), {"cuentas": data}, lambda: read_accounts(kind))


def save_local_accounts(accounts: dict[str, dict]) -> None:
    save_accounts(PASSWORD, accounts)


def save_totp_accounts(accounts: dict[str, dict]) -> None:
    save_accounts(TOTP, accounts)


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

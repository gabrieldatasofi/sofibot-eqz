"""Who sees which report when users sign in with Microsoft Entra ID (docs/09-inicio-sesion-entra.md).

Permissions are granted on Gold tables. Entra puts the user's app roles in the sign-in token;
reports/permisos.json maps each role to the Gold tables it may see ("*" = all). A report is
visible when the user's roles, together, cover every table the report reads (its report.json
"tables"): a report is built in advance for everyone, so it cannot show only part of itself.
The file is read on every request, so a change applies without restarting the portal.
"""
import json
import logging
import os
import re

from . import config

ALL = "*"
TABLE = re.compile(r"\w+\.\w+")
log = logging.getLogger("sofibot")


class PermissionsError(Exception):
    pass


def permissions_file():
    return config.REPORTS_DIR / "permisos.json"


def read() -> dict[str, set[str]]:
    """Role -> Gold tables (lower case) or {"*"}. Raises PermissionsError if missing or malformed."""
    path = permissions_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PermissionsError(f"{path} does not exist") from exc
    except (OSError, ValueError) as exc:
        raise PermissionsError(f"{path}: {exc}") from exc
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


def granted(roles, permissions: dict[str, set[str]]) -> set[str]:
    """Union of the tables of every role the user has."""
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

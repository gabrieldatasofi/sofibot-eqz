"""Read-only access to the Gold tables of a SQL Server warehouse.

Settings come from environment variables (docs/configuracion.md). The login must only
have SELECT on the Gold schema (sql/crear-login-lectura.sql): that permission, not this
module, is what makes the access read-only.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
import re
from typing import Any, Iterator, Sequence

import pyodbc

# Pooling keeps idle sessions open on the server; reports open few, short connections.
pyodbc.pooling = False

AUTH_MODES = ("sql", "windows", "entra-sp")


def _odbc_value(value: str) -> str:
    """Quote a connection-string value so ';', '{' or '}' in a password cannot inject attributes."""
    return "{" + value.replace("}", "}}") + "}"


@dataclass(frozen=True)
class Settings:
    host: str
    database: str
    port: str = "1433"
    auth: str = "sql"
    user: str = ""
    password: str = ""
    schema: str = "gold"
    driver: str = "ODBC Driver 18 for SQL Server"
    encrypt: str = "yes"
    trust_certificate: bool = False
    login_timeout: int = 15
    query_timeout: int = 300

    @classmethod
    def from_environment(cls, env=os.environ) -> "Settings":
        auth = env.get("SQLSERVER_AUTH", "sql")
        if auth not in AUTH_MODES:
            raise RuntimeError(f"SQLSERVER_AUTH must be one of {', '.join(AUTH_MODES)}")
        required = ["SQLSERVER_HOST", "SQLSERVER_DATABASE"]
        if auth != "windows":
            required += ["SQLSERVER_USER", "SQLSERVER_PASSWORD"]
        missing = [name for name in required if not env.get(name)]
        if missing:
            raise RuntimeError(f"Missing settings: {', '.join(missing)} (see .env.example)")
        return cls(
            host=env["SQLSERVER_HOST"],
            database=env["SQLSERVER_DATABASE"],
            port=env.get("SQLSERVER_PORT", cls.port),
            auth=auth,
            user=env.get("SQLSERVER_USER", ""),
            password=env.get("SQLSERVER_PASSWORD", ""),
            schema=env.get("SQLSERVER_GOLD_SCHEMA", cls.schema),
            driver=env.get("SQLSERVER_DRIVER", cls.driver),
            encrypt=env.get("SQLSERVER_ENCRYPT", cls.encrypt),
            trust_certificate=env.get("SQLSERVER_TRUST_CERTIFICATE") == "1",
            login_timeout=int(env.get("SQLSERVER_LOGIN_TIMEOUT", cls.login_timeout)),
            query_timeout=int(env.get("SQLSERVER_QUERY_TIMEOUT", cls.query_timeout)),
        )

    @property
    def server(self) -> str:
        # host,port for a fixed port; a named instance (host\instance) can leave the port empty.
        return f"{self.host},{self.port}" if self.port else self.host

    def connection_string(self) -> str:
        parts = {
            "DRIVER": _odbc_value(self.driver),
            "SERVER": self.server,
            "DATABASE": _odbc_value(self.database),
            "Encrypt": self.encrypt,
            "TrustServerCertificate": "yes" if self.trust_certificate else "no",
            "ApplicationIntent": "ReadOnly",  # uses a readable secondary replica when there is one
            "APP": "sofibot-eqz",
        }
        if self.auth == "windows":
            parts["Trusted_Connection"] = "yes"
        else:
            if self.auth == "entra-sp":  # Azure SQL / Fabric: user = application (client) ID
                parts["Authentication"] = "ActiveDirectoryServicePrincipal"
            parts["UID"] = _odbc_value(self.user)
            parts["PWD"] = _odbc_value(self.password)
        return ";".join(f"{key}={value}" for key, value in parts.items())


# Driver messages are cryptic; these point to the fix (docs/solucion-de-problemas.md).
HINTS = [
    (("certificate verify failed", "certificate chain was issued", "self-signed certificate", "self signed certificate"),
     "El certificado TLS del SQL Server no es de confianza (autofirmado o de una CA interna). Solución "
     "recomendada: instalar en el SQL Server un certificado válido. Solo para pruebas o una red controlada: "
     "SQLSERVER_TRUST_CERTIFICATE=1 en .env, que desactiva la comprobación del certificado."),
    (("login failed",),
     "SQL Server ha rechazado el usuario o la contraseña. Revisa SQLSERVER_USER y SQLSERVER_PASSWORD, que la "
     "autenticación de SQL Server esté activada y vuelve a ejecutar sql/crear-login-lectura.sql si hace falta. "
     "Si la contraseña tiene acentos o ñ y el script se ejecutó con sqlcmd sin -f 65001, se guardó otra distinta."),
    (("cannot open database",),
     "El login no tiene acceso a esa base de datos o el nombre es incorrecto: revisa SQLSERVER_DATABASE."),
    (("login timeout expired", "tcp provider", "server was not found", "network-related", "0x2749", "0x274c"),
     "No se llega al servidor: revisa SQLSERVER_HOST y SQLSERVER_PORT, el firewall o la VPN, y que TCP/IP esté "
     "habilitado en SQL Server. Prueba el puerto desde este equipo (Test-NetConnection / nc -vz)."),
    (("can't open lib", "data source name not found"),
     "No está instalado el ODBC Driver 18 for SQL Server (solo pasa fuera de Docker)."),
    (("unsupported protocol", "ssl handshake"),
     "El SQL Server no admite TLS 1.2: necesita una actualización o parche de seguridad."),
]


def connection_hint(error: Exception | str) -> str | None:
    """A one-line explanation of a connection error, or None if it is not a known one."""
    message = str(error).casefold()
    for patterns, hint in HINTS:
        if any(pattern in message for pattern in patterns):
            return hint
    return None


# Report builds pass the tables declared in report.json (projects.build); queries may only read those.
DECLARED_TABLES_VARIABLE = "SOFIBOT_REPORT_TABLES"
_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_IDENTIFIER = r'(?:\[(?:[^\]]|\]\])+\]|"(?:[^"]|"")+"|[A-Za-z_@#][\w@$#]*)'
_DOTTED = re.compile(rf"{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})+")
_PART = re.compile(_IDENTIFIER)


def _unquote(identifier: str) -> str:
    if identifier[0] == "[":
        return identifier[1:-1].replace("]]", "]")
    if identifier[0] == '"':
        return identifier[1:-1].replace('""', '"')
    return identifier


def referenced_tables(sql: str, schema: str = "gold") -> set[str]:
    """'schema.table' names of the Gold schema that a statement mentions, lower case.

    Recognises gold.t, [gold].[t], "gold"."t" and db.gold.t. It is a check against mistakes
    (a report reading a table it does not declare), not a SQL parser: an alias called like the
    schema reads as a table and makes the check stricter, never looser.
    """
    schema = schema.casefold()
    found = set()
    for chain in _DOTTED.finditer(_COMMENTS.sub(" ", sql)):
        parts = [_unquote(part).casefold() for part in _PART.findall(chain.group(0))]
        found.update(f"{schema}.{table}" for owner, table in zip(parts, parts[1:]) if owner == schema)
    return found


class UndeclaredTableError(Exception):
    pass


class Gold:
    """Short-lived, parameterized, read-only queries over the Gold schema."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_environment()

    def check_declared(self, sql: str) -> None:
        """During a report build, refuse queries over Gold tables missing from report.json 'tables'."""
        declared = os.environ.get(DECLARED_TABLES_VARIABLE)
        if declared is None:
            return
        allowed = {name.strip().casefold() for name in declared.split(",") if name.strip()}
        undeclared = sorted(referenced_tables(sql, self.settings.schema) - allowed)
        if undeclared:
            raise UndeclaredTableError(
                f"The query reads {', '.join(undeclared)}, which report.json does not list in 'tables'. "
                "Add it there: the portal decides who sees the report from those tables.")

    @contextmanager
    def connect(self) -> Iterator[pyodbc.Connection]:
        connection = pyodbc.connect(
            self.settings.connection_string(), timeout=self.settings.login_timeout, readonly=True, autocommit=True
        )
        connection.timeout = self.settings.query_timeout  # per-statement limit, in seconds
        try:
            yield connection
        finally:
            connection.close()

    def query(self, sql: str, parameters: Sequence[Any] = (), *, connection: pyodbc.Connection | None = None):
        """Run one statement with `?` placeholders; returns (column names, rows as tuples)."""
        self.check_declared(sql)
        if connection is None:
            with self.connect() as connection:
                return self.query(sql, parameters, connection=connection)
        cursor = connection.cursor()
        try:
            cursor.execute(sql, *parameters)
            columns = [column[0] for column in cursor.description]
            return columns, [tuple(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def dataframe(self, sql: str, parameters: Sequence[Any] = (), *, connection: pyodbc.Connection | None = None):
        """Same as query(), as a pandas DataFrame."""
        import pandas as pd

        columns, rows = self.query(sql, parameters, connection=connection)
        return pd.DataFrame.from_records(rows, columns=columns)

    def server_info(self) -> dict:
        """Connection check without reading rows: server, login, permissions and Gold tables."""
        schema = self.settings.schema
        with self.connect() as connection:
            _, rows = self.query(
                "SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(64)), "
                "CAST(SERVERPROPERTY('Edition') AS nvarchar(128)), DB_NAME(), SUSER_SNAME(), "
                "SCHEMA_ID(?), IS_ROLEMEMBER('db_owner'), HAS_PERMS_BY_NAME(?, 'SCHEMA', 'INSERT'), "
                "HAS_PERMS_BY_NAME(?, 'SCHEMA', 'SELECT')",
                [schema, schema, schema], connection=connection,
            )
            version, edition, database, login, schema_id, is_owner, can_write, can_read = rows[0]
            _, tables = self.query(
                "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ? ORDER BY TABLE_NAME",
                [schema], connection=connection,
            )
        return {
            "server": self.settings.server, "version": version, "edition": edition,
            "database": database, "login": login, "schema": schema,
            "schema_exists": schema_id is not None, "can_read_schema": bool(can_read),
            # A reporting login should never own the database or be able to write.
            "read_only_login": not is_owner and not can_write,
            "tables": [{"name": f"{schema}.{name}", "type": "view" if kind == "VIEW" else "table"} for name, kind in tables],
        }

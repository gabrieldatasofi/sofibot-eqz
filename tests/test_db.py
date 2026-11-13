import pytest

from sofibot_eqz import Settings

BASE = {"SQLSERVER_HOST": "db.example", "SQLSERVER_DATABASE": "dw",
        "SQLSERVER_USER": "reader", "SQLSERVER_PASSWORD": "p;w}d"}


def test_password_cannot_inject_attributes():
    text = Settings.from_environment(BASE).connection_string()
    assert "PWD={p;w}}d}" in text
    assert "SERVER=db.example,1433" in text
    assert "ApplicationIntent=ReadOnly" in text and "TrustServerCertificate=no" in text


def test_named_instance_without_port():
    settings = Settings.from_environment({**BASE, "SQLSERVER_HOST": r"srv\GOLD", "SQLSERVER_PORT": ""})
    assert settings.server == r"srv\GOLD"


def test_missing_settings_are_named():
    with pytest.raises(RuntimeError, match="SQLSERVER_PASSWORD"):
        Settings.from_environment({k: v for k, v in BASE.items() if k != "SQLSERVER_PASSWORD"})


def test_windows_and_entra_authentication():
    windows = Settings.from_environment({"SQLSERVER_HOST": "h", "SQLSERVER_DATABASE": "d", "SQLSERVER_AUTH": "windows"})
    assert "Trusted_Connection=yes" in windows.connection_string() and "PWD" not in windows.connection_string()
    entra = Settings.from_environment({**BASE, "SQLSERVER_AUTH": "entra-sp"})
    assert "Authentication=ActiveDirectoryServicePrincipal" in entra.connection_string()
    with pytest.raises(RuntimeError):
        Settings.from_environment({**BASE, "SQLSERVER_AUTH": "kerberos"})


def test_connection_errors_get_a_hint():
    from sofibot_eqz.db import connection_hint

    tls = "[08001] SSL Provider: [error:0A000086:SSL routines::certificate verify failed:self-signed certificate]"
    assert "SQLSERVER_TRUST_CERTIFICATE" in connection_hint(tls)
    assert "SQLSERVER_PASSWORD" in connection_hint("[28000] Login failed for user 'x'. (18456)")
    assert "SQLSERVER_HOST" in connection_hint("[HYT00] Login timeout expired (0)")
    assert connection_hint("something else") is None


# --- Gold tables a query reads (report.json "tables") -----------------------------------

@pytest.mark.parametrize("sql, expected", [
    ("SELECT a FROM gold.month_store WHERE b = ?", {"gold.month_store"}),
    ("SELECT * FROM [gold].[Month Store] s JOIN \"GOLD\".\"x\" ON 1=1", {"gold.month store", "gold.x"}),
    ("SELECT * FROM ContosoDW.gold.month_product", {"gold.month_product"}),
    ("SELECT * FROM gold . month_store /* gold.oculta */ -- gold.otra", {"gold.month_store"}),
    ("SELECT s.month FROM gold.month_store AS s", {"gold.month_store"}),
    ("SELECT name FROM INFORMATION_SCHEMA.TABLES", set()),
])
def test_referenced_tables(sql, expected):
    from sofibot_eqz.db import referenced_tables

    assert referenced_tables(sql) == expected


def test_builds_only_query_declared_tables(monkeypatch):
    from sofibot_eqz.db import Gold, UndeclaredTableError

    gold = Gold(Settings(host="h", database="d", user="u", password="p"))
    gold.check_declared("SELECT * FROM gold.otra")  # outside a build: no check
    monkeypatch.setenv("SOFIBOT_REPORT_TABLES", "gold.month_store")
    gold.check_declared("SELECT * FROM [gold].[MONTH_STORE]")
    with pytest.raises(UndeclaredTableError, match="gold.month_product"):
        gold.check_declared("SELECT * FROM gold.month_store s JOIN gold.month_product p ON 1 = 1")
    with pytest.raises(UndeclaredTableError):  # refused before connecting to anything
        gold.query("SELECT * FROM gold.month_product")

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

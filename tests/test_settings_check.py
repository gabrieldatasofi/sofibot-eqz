from sofibot_eqz import cli
from sofibot_eqz.settings_check import review

SECRETS = {"SQLSERVER_HOST": "servidor-secreto.local", "SQLSERVER_DATABASE": "BaseSecreta",
           "SQLSERVER_USER": "usuario_secreto", "SQLSERVER_PASSWORD": "Contraseña-Secreta-1",
           "SOFIBOT_ADMIN_TOKEN": "t" * 40}


def _printed(lines, problems):
    return "\n".join(lines + problems)


def test_complete_portal_settings_show_no_values():
    lines, problems = review(dict(SECRETS, SQLSERVER_GOLD_SCHEMA="dbo"))
    assert problems == []
    text = _printed(lines, problems)
    for value in SECRETS.values():
        assert value not in text
    assert "dbo" in text and "rellena" in text


def test_missing_and_short_settings_are_named():
    lines, problems = review({"SQLSERVER_HOST": "x", "SOFIBOT_ADMIN_TOKEN": "corto"})
    text = "\n".join(problems)
    assert "SQLSERVER_DATABASE" in text and "SQLSERVER_PASSWORD" in text
    assert "SOFIBOT_ADMIN_TOKEN" in text


def test_entra_sign_in_needs_its_settings_without_showing_them():
    env = dict(SECRETS, SOFIBOT_AUTH="entra", ENTRA_TENANT_ID="tenant-secreto",
               SOFIBOT_PUBLIC_URL="https://portal-secreto.local")
    lines, problems = review(env)
    assert any("ENTRA_CLIENT_SECRET" in p for p in problems)
    text = _printed(lines, problems)
    assert "tenant-secreto" not in text and "portal-secreto" not in text


def test_query_service_needs_its_own_login():
    env = dict(SECRETS, SQLSERVER_USER="sofibot_lectura", SOFIBOT_QUERY_ENABLED="1",
               ENTRA_TENANT_ID="a", ENTRA_CLIENT_ID="b")
    lines, problems = review(env, service="consultas")
    assert any("sofibot_consultas" in p for p in problems)
    lines, problems = review(dict(env, SQLSERVER_USER="sofibot_consultas"), service="consultas")
    assert problems == []


def test_cli_exit_code_and_output(monkeypatch, capsys):
    for name in list(SECRETS) + ["SOFIBOT_AUTH", "SOFIBOT_VIEWER_PASSWORD", "SOFIBOT_CODE_API", "SOFIBOT_API_TOKEN"]:
        monkeypatch.delenv(name, raising=False)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    assert "Configuración completa" in out
    assert "Contraseña-Secreta-1" not in out
    monkeypatch.delenv("SQLSERVER_PASSWORD")
    assert cli.main(["config"]) == 1

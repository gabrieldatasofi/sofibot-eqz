"""Local accounts (acceso/cuentas-locales.json and, with TOTP, cuentas-totp.json): sign-in without
Entra ID, roles, Sofibot's own tokens."""
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from sofibot_eqz import access, auth, cli, identity
from test_consultas import FakeGold, entries, service  # noqa: F401 (fixtures)
from test_drafts import api, contract  # noqa: F401 (fixtures)
from test_pages import CONTRACT, csrf
from test_access import CLIENT, ENTRA, TENANT, FakeEntra, built_report, grant

SECRET = "s" * 40
PASSWORD = "una-contraseña-larga"
EVERYTHING = [*identity.FUNCTION_ROLES, "*"]


def add_account(name="sofibot.admin", roles=EVERYTHING, password=PASSWORD, version=1):
    accounts = {n: dict(a) for n, a in access.read_local_accounts().items()}
    accounts[name] = {"nombre": "Administrador", "hash": identity.hash_password(password), "version": version,
                      "roles": roles}
    access.save_local_accounts(accounts)


@pytest.fixture(autouse=True)
def fresh_failures(monkeypatch):
    auth._failures.clear()
    auth._used_steps.clear()
    monkeypatch.delenv("SOFIBOT_LOCAL_ACCOUNTS", raising=False)


@pytest.fixture
def local_portal(folders, monkeypatch):
    monkeypatch.setenv("SOFIBOT_AUTH", "local")
    monkeypatch.setenv("SOFIBOT_LOCAL_SECRET", SECRET)
    for name in ("SOFIBOT_QUERY_URL", "SOFIBOT_CODE_API", "SOFIBOT_API_TOKEN", "SQLSERVER_HOST",
                 "ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    (folders / "reports" / "gold_schema.json").write_text(json.dumps(CONTRACT))
    (folders / "reports" / "permisos.json").write_text(json.dumps({"roles": {"Ventas": ["gold.ventas"]}}))
    built_report(folders, "ventas")
    add_account()
    from sofibot_eqz.server import app

    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def local_sign_in(client, name="sofibot.admin", password=PASSWORD, next_path="/explore"):
    form = client.get(f"/auth/login?next={next_path}")
    return client.post("/auth/local", data={"csrf": csrf(form.text), "next": next_path,
                                            "usuario": name, "contrasena": password})


# --- Passwords and the accounts file ------------------------------------------------------

def test_passwords_are_hashed_with_scrypt():
    stored = identity.hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert identity.password_matches(PASSWORD, stored)
    assert not identity.password_matches(PASSWORD + "x", stored)
    assert not identity.password_matches(PASSWORD, "otro$formato")
    with pytest.raises(ValueError):
        identity.hash_password("corta")


def test_accounts_file_is_checked(folders):
    assert access.read_local_accounts() == {}
    add_account()
    assert access.read_local_accounts()["sofibot.admin"]["roles"] == tuple(sorted(EVERYTHING))
    path = access.local_accounts_file()
    path.write_text(json.dumps({"cuentas": {"ana@empresa.test": {"hash": "x", "version": 1, "roles": []}}}))
    with pytest.raises(access.PermissionsError):
        access.read_local_accounts()  # an e-mail is an Entra user, never a local account
    assert access.load_local_accounts() == {}


def test_star_role_gives_every_table():
    assert access.granted(("Sofibot.Admin", "*"), {"Ventas": {"gold.ventas"}}) == {"*"}
    assert access.covers(access.granted(("*",), {}), ["gold.lo_que_sea"])


# --- Portal sign-in -----------------------------------------------------------------------

def test_local_mode_signs_in_with_user_and_password(local_portal):
    landing = local_portal.get("/")
    assert landing.status_code == 200 and "Iniciar sesión con Microsoft" not in landing.text
    assert local_portal.get("/explore").headers["location"].startswith("/auth/login")
    form = local_portal.get("/auth/login")
    assert 'name="contrasena"' in form.text and "Microsoft" not in form.text
    assert local_sign_in(local_portal, password="mal").headers["location"].endswith("error=1")
    assert local_portal.get("/explore").status_code == 302
    response = local_sign_in(local_portal)
    assert response.status_code == 303 and response.headers["location"] == "/explore"
    page = local_portal.get("/explore").text
    assert "cuenta local" in page and "Administración" in page and "Revisión" in page
    assert local_portal.get("/output/ventas/").status_code == 200  # "*": every report
    admin = local_portal.get("/admin").text
    assert "Solo cuentas locales" in admin and "sofibot.admin" in admin and "Configurado" in admin
    assert "scrypt" not in admin and SECRET not in admin
    users = local_portal.get("/admin/usuarios").text
    assert "Cuentas locales" in users and "todas las tablas" in users


def test_login_form_needs_its_csrf_token(local_portal):
    local_portal.get("/auth/login")
    response = local_portal.post("/auth/local", data={"csrf": "otro", "usuario": "sofibot.admin", "contrasena": PASSWORD})
    assert response.headers["location"].endswith("error=3")
    assert local_portal.get("/explore").status_code == 302


def test_repeated_failures_block_the_account_for_a_while(local_portal):
    for _ in range(auth.FAILURES):
        assert local_sign_in(local_portal, password="mal").headers["location"].endswith("error=1")
    assert local_sign_in(local_portal).headers["location"].endswith("error=2")  # even the right password
    assert local_portal.get("/explore").status_code == 302


def test_changing_the_password_ends_the_session(local_portal):
    local_sign_in(local_portal)
    assert local_portal.get("/explore").status_code == 200
    add_account(version=2)
    assert local_portal.get("/explore").headers["location"].startswith("/auth/login")


def test_roles_come_from_the_account(local_portal):
    add_account("tienda", roles=["Ventas"])
    local_sign_in(local_portal, "tienda")
    page = local_portal.get("/explore").text
    assert "Administración" not in page and local_portal.get("/admin").status_code == 403


def test_entra_mode_offers_both_ways_in(folders, monkeypatch):
    for name, value in ENTRA.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SOFIBOT_QUERY_URL", raising=False)
    (folders / "reports" / "permisos.json").write_text(json.dumps({"roles": {"Ventas": ["gold.ventas"]}}))
    built_report(folders, "ventas")
    from sofibot_eqz.server import app

    client = TestClient(app, base_url="https://testserver", follow_redirects=False)
    grant("ana@empresa.test", ["Ventas"])
    claims = {"tid": TENANT, "aud": CLIENT, "name": "Ana", "preferred_username": "ana@empresa.test"}
    monkeypatch.setattr(auth, "_client", lambda settings: FakeEntra(claims))
    assert client.get("/auth/login").headers["location"].startswith("https://login.test/")  # no local account
    assert "Iniciar sesión con Microsoft" in client.get("/").text
    add_account()
    landing = client.get("/").text
    assert "Iniciar sesión con Microsoft" not in landing and "cuenta local de Sofibot" in landing
    form = client.get("/auth/login?next=/informes").text
    assert "/auth/microsoft?next=/informes" in form and 'name="contrasena"' in form
    local_sign_in(client)
    assert "Administración" in client.get("/explore").text
    # An Entra user still signs in through Microsoft (the button), with roles from usuarios.json.
    client.cookies.clear()
    assert client.get("/auth/microsoft").headers["location"].startswith("https://login.test/")
    assert client.get("/auth/callback", params={"code": "c1", "state": "s1"}).status_code == 302
    page = client.get("/explore").text
    assert "Ana" in page and "Administración" not in page and "cuenta local" not in page


# --- Sofibot's own tokens -----------------------------------------------------------------

def test_tokens_identify_the_account_until_its_password_changes(folders, monkeypatch):
    monkeypatch.setenv("SOFIBOT_LOCAL_SECRET", SECRET)
    add_account()
    account = access.read_local_accounts()["sofibot.admin"]
    token = identity.issue_token("sofibot.admin", account, minutes=5)
    who = identity.from_bearer(f"Bearer {token}")
    assert (who.email, who.via, who.has("Sofibot.Autor"), who.tables({})) == ("sofibot.admin", "local", True, None)
    forged = jwt.encode({**jwt.decode(token, options={"verify_signature": False})}, "x" * 40, algorithm="HS256")
    with pytest.raises(identity.IdentityError):
        identity.from_bearer(f"Bearer {forged}")
    expired = identity.issue_token("sofibot.admin", account, minutes=-10)
    with pytest.raises(identity.IdentityError):
        identity.from_bearer(f"Bearer {expired}")
    add_account(version=2)
    with pytest.raises(identity.IdentityError, match="password has changed"):
        identity.from_bearer(f"Bearer {token}")
    monkeypatch.delenv("SOFIBOT_LOCAL_SECRET")
    with pytest.raises(identity.IdentityError, match="SOFIBOT_LOCAL_SECRET"):
        identity.from_bearer(f"Bearer {token}")


def test_secret_must_be_long_and_its_own(monkeypatch):
    monkeypatch.setenv("SOFIBOT_LOCAL_SECRET", "corto")
    assert identity.local_secret() is None
    monkeypatch.setenv("SOFIBOT_LOCAL_SECRET", SECRET)
    monkeypatch.setenv("SOFIBOT_ADMIN_TOKEN", SECRET)
    assert identity.local_secret() is None


def test_report_api_accepts_a_local_token(api, contract, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SOFIBOT_CODE_API", "local")
    monkeypatch.setenv("SOFIBOT_LOCAL_SECRET", SECRET)
    add_account()
    add_account("lector", roles=["Ventas"])
    accounts = access.read_local_accounts()
    author = {"Authorization": "Bearer " + identity.issue_token("sofibot.admin", accounts["sofibot.admin"], 5)}
    reader = {"Authorization": "Bearer " + identity.issue_token("lector", accounts["lector"], 5)}
    assert api.get("/api/code/schema", headers=author).status_code == 200
    assert api.get("/api/code/schema", headers=reader).status_code == 403


def test_query_service_accepts_a_local_token(service, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SOFIBOT_LOCAL_SECRET", SECRET)
    add_account()
    token = identity.issue_token("sofibot.admin", access.read_local_accounts()["sofibot.admin"], 5)
    response = service.get("/api/query/catalog", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200 and response.json()["tables"]


def test_connect_page_gives_a_local_account_its_token(local_portal, monkeypatch):
    monkeypatch.setenv("SOFIBOT_CODE_API", "local")
    local_sign_in(local_portal)
    page = local_portal.get("/conectar").text
    assert "Generar token personal" in page and "Descargar el conector" not in page
    assert local_portal.post("/conectar/token", data={"csrf": "otro"}).status_code == 303
    response = local_portal.post("/conectar/token", data={"csrf": csrf(page)})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert "SOFIBOT_API_TOKEN" in response.text and "SOFIBOT_ENTRA_TENANT_ID" not in response.text
    token = response.text.split("<pre><code>", 1)[1].split("</code>", 1)[0]
    assert identity.from_bearer(f"Bearer {token}").email == "sofibot.admin"
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - time.time() > 29 * 24 * 3600


def test_portal_queries_forward_a_short_local_token(local_portal, monkeypatch):
    from sofibot_eqz import pages

    monkeypatch.setenv("SOFIBOT_QUERY_URL", "http://consultas:8080")
    seen = []

    def fake(method, route, token, payload=None):
        seen.append(identity.from_bearer(f"Bearer {token}").email)
        return 200, {"tables": {}}

    monkeypatch.setattr(pages, "call_query_service", fake)
    local_sign_in(local_portal)
    assert "No tienes tablas consultables" in local_portal.get("/consultas").text
    assert seen == ["sofibot.admin"]


# --- Command line -------------------------------------------------------------------------

def test_cli_manages_local_accounts(folders, monkeypatch, capsys):
    assert cli.main(["local-account", "add", "sofibot.admin", "--generate"]) == 0
    out = capsys.readouterr().out
    password = out.split("\n\n    ", 1)[1].split("\n", 1)[0]
    account = access.read_local_accounts()["sofibot.admin"]
    assert identity.password_matches(password, account["hash"]) and "*" in account["roles"]
    assert password not in access.local_accounts_file().read_text()
    assert cli.main(["local-account", "add", "sofibot.admin", "--generate"]) == 1
    assert cli.main(["local-account", "add", "ana@empresa.test", "--generate"]) == 2
    answers = iter(["nueva-contraseña-larga", "nueva-contraseña-larga"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli.main(["local-account", "passwd", "sofibot.admin"]) == 0
    account = access.read_local_accounts()["sofibot.admin"]
    assert account["version"] == 2 and identity.password_matches("nueva-contraseña-larga", account["hash"])
    assert cli.main(["local-account", "roles", "sofibot.admin", "Sofibot.Admin", "Ventas"]) == 0
    assert access.read_local_accounts()["sofibot.admin"]["roles"] == ("Sofibot.Admin", "Ventas")
    assert cli.main(["local-account", "revoke", "sofibot.admin"]) == 0
    assert access.read_local_accounts()["sofibot.admin"]["version"] == 3
    assert cli.main(["local-account", "remove", "sofibot.admin"]) == 0
    assert access.read_local_accounts() == {}
    assert "scrypt" not in capsys.readouterr().out


def test_full_access_accounts_are_labelled(local_portal, capsys):
    assert identity.full_access(EVERYTHING) and not identity.full_access(["*"])
    assert not identity.full_access([*identity.FUNCTION_ROLES, "Ventas"])
    add_account("tienda", roles=["Ventas"])
    local_sign_in(local_portal)
    users = local_portal.get("/admin/usuarios").text
    assert users.count('class="tag total"') == 2  # sofibot.admin, and the legend; not tienda
    assert "sofibot.admin (acceso total)" in local_portal.get("/admin").text
    assert "tienda (acceso total)" not in local_portal.get("/admin").text
    assert cli.main(["local-account"]) == 0
    listing = capsys.readouterr().out
    assert "sofibot.admin:" in listing and listing.count("FULL ACCESS") == 1

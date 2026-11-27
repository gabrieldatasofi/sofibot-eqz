"""Local accounts with TOTP (acceso/cuentas-totp.json): password, then a code from an authenticator app."""
import base64
import json
import time

import pytest

from sofibot_eqz import access, auth, cli, identity
from test_local_accounts import EVERYTHING, PASSWORD, add_account, local_portal, local_sign_in  # noqa: F401 (fixtures)
from test_pages import csrf

# RFC 6238, appendix B (SHA1): the key "12345678901234567890".
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
SECRET = identity.new_totp_secret()


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    auth._failures.clear()
    auth._used_steps.clear()
    monkeypatch.delenv("SOFIBOT_LOCAL_ACCOUNTS", raising=False)


def now_code(secret=SECRET, shift=0):
    return identity.totp_code(secret, int(time.time() // identity.TOTP_PERIOD) + shift)


def add_totp_account(name="ana.totp", roles=EVERYTHING, secret=SECRET, version=1):
    accounts = {n: dict(a) for n, a in access.read_totp_accounts().items()}
    accounts[name] = {"nombre": "Ana", "hash": identity.hash_password(PASSWORD), "version": version,
                      "roles": roles, "totp": secret}
    access.save_totp_accounts(accounts)


def send_code(client, code):
    form = client.get("/auth/codigo")
    assert form.status_code == 200, form.headers.get("location")
    return client.post("/auth/codigo", data={"csrf": csrf(form.text), "codigo": code})


# --- TOTP codes ---------------------------------------------------------------------------

def test_codes_match_rfc_6238():
    for seconds, code in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
        assert identity.totp_code(RFC_SECRET, seconds // 30) == code
        assert identity.totp_step(RFC_SECRET, code, now=seconds) == seconds // 30


def test_codes_allow_one_step_of_clock_drift_and_nothing_else():
    at = 1111111109
    step = at // 30
    assert identity.totp_step(RFC_SECRET, identity.totp_code(RFC_SECRET, step - 1), now=at) == step - 1
    assert identity.totp_step(RFC_SECRET, identity.totp_code(RFC_SECRET, step + 1), now=at) == step + 1
    assert identity.totp_step(RFC_SECRET, identity.totp_code(RFC_SECRET, step - 2), now=at) is None
    assert identity.totp_step(RFC_SECRET, "081 804", now=at) == step  # spaces as the app shows it
    for wrong in ("", "12345", "1234567", "abcdef", None):
        assert identity.totp_step(RFC_SECRET, wrong, now=at) is None


def test_new_secrets_are_random_base32_for_the_apps():
    assert len(SECRET) == 32 and access.BASE32.fullmatch(SECRET) and identity.new_totp_secret() != SECRET
    uri = identity.totp_uri("ana.totp", SECRET)
    assert uri.startswith("otpauth://totp/Sofibot:ana.totp?secret=" + SECRET) and "issuer=Sofibot" in uri


# --- The accounts file --------------------------------------------------------------------

def test_totp_file_is_checked_and_kept_apart(folders):
    add_account("solo.clave")
    add_totp_account()
    accounts = access.load_local_accounts()
    assert accounts["solo.clave"]["totp"] is None and accounts["ana.totp"]["totp"] == SECRET
    assert accounts["ana.totp"]["tipo"] == access.TOTP
    assert SECRET not in access.local_accounts_file().read_text()
    path = access.totp_accounts_file()
    path.write_text(json.dumps({"cuentas": {"ana.totp": {"hash": "x", "version": 1, "roles": []}}}))
    with pytest.raises(access.PermissionsError, match="totp"):
        access.read_totp_accounts()
    assert set(access.load_local_accounts()) == {"solo.clave"}  # a broken file stops only its own accounts


def test_a_name_in_both_files_signs_in_with_neither(folders):
    add_account("ana.totp")
    add_totp_account()
    assert access.load_local_accounts() == {}


def test_kinds_of_account_can_be_switched_off(folders, monkeypatch):
    add_account("solo.clave")
    add_totp_account()
    monkeypatch.setenv("SOFIBOT_LOCAL_ACCOUNTS", "totp")
    assert set(access.load_local_accounts()) == {"ana.totp"}
    monkeypatch.setenv("SOFIBOT_LOCAL_ACCOUNTS", "password")
    assert set(access.load_local_accounts()) == {"solo.clave"}
    monkeypatch.setenv("SOFIBOT_LOCAL_ACCOUNTS", "password, totp")
    assert set(access.load_local_accounts()) == {"solo.clave", "ana.totp"}
    monkeypatch.setenv("SOFIBOT_LOCAL_ACCOUNTS", "sms")
    assert access.load_local_accounts() == {}
    monkeypatch.setenv("SOFIBOT_AUTH", "local")
    with pytest.raises(RuntimeError, match="SOFIBOT_LOCAL_ACCOUNTS"):
        auth.check_settings()


# --- Portal sign-in -----------------------------------------------------------------------

def test_totp_account_needs_the_code_after_the_password(local_portal):
    add_totp_account()
    assert local_portal.get("/auth/codigo").headers["location"].endswith("error=3")  # no password yet
    response = local_sign_in(local_portal, "ana.totp")
    assert response.status_code == 303 and response.headers["location"] == "/auth/codigo"
    assert local_portal.get("/explore").status_code == 302  # the password alone is not enough
    form = local_portal.get("/auth/codigo").text
    assert 'name="codigo"' in form and "ana.totp" in form and SECRET not in form
    assert send_code(local_portal, "000000" if now_code() != "000000" else "111111").headers["location"].endswith("error=1")
    response = send_code(local_portal, now_code())
    assert response.status_code == 303 and response.headers["location"] == "/explore"
    page = local_portal.get("/explore").text
    assert "cuenta local" in page and "Administración" in page
    admin = local_portal.get("/admin").text
    assert "ana.totp" in admin and "TOTP" in admin and SECRET not in admin
    assert "TOTP" in local_portal.get("/admin/usuarios").text


def test_a_code_works_only_once(local_portal):
    add_totp_account()
    code = now_code()
    local_sign_in(local_portal, "ana.totp")
    assert send_code(local_portal, code).headers["location"] == "/explore"
    local_portal.get("/auth/logout")
    local_sign_in(local_portal, "ana.totp")
    assert send_code(local_portal, code).headers["location"].endswith("error=1")  # someone who saw it
    assert local_portal.get("/explore").status_code == 302


def test_wrong_codes_count_towards_the_block(local_portal):
    add_totp_account()
    local_sign_in(local_portal, "ana.totp")
    wrong = "000000" if now_code() != "000000" else "111111"
    for _ in range(auth.FAILURES):
        assert send_code(local_portal, wrong).headers["location"].endswith("error=1")
    assert send_code(local_portal, now_code()).headers["location"].endswith("error=2")  # even the right one
    assert local_sign_in(local_portal, "ana.totp").headers["location"].endswith("error=2")


def test_the_code_step_expires(local_portal, monkeypatch):
    add_totp_account()
    local_sign_in(local_portal, "ana.totp")
    monkeypatch.setattr(auth, "TOTP_MINUTES", -1)
    assert local_portal.get("/auth/codigo").headers["location"].endswith("error=3")


def test_code_form_needs_its_csrf_token(local_portal):
    add_totp_account()
    local_sign_in(local_portal, "ana.totp")
    response = local_portal.post("/auth/codigo", data={"csrf": "otro", "codigo": now_code()})
    assert response.headers["location"].endswith("error=3")
    assert local_portal.get("/explore").status_code == 302


def test_switching_password_accounts_off_ends_their_sessions(local_portal, monkeypatch):
    add_totp_account()
    local_sign_in(local_portal)  # sofibot.admin: password only
    assert local_portal.get("/explore").status_code == 200
    monkeypatch.setenv("SOFIBOT_LOCAL_ACCOUNTS", "totp")
    assert local_portal.get("/explore").headers["location"].startswith("/auth/login")
    assert local_sign_in(local_portal).headers["location"].endswith("error=1")
    assert local_sign_in(local_portal, "ana.totp").headers["location"] == "/auth/codigo"


def test_a_new_secret_ends_the_session(local_portal):
    add_totp_account()
    local_sign_in(local_portal, "ana.totp")
    send_code(local_portal, now_code())
    assert local_portal.get("/explore").status_code == 200
    add_totp_account(secret=identity.new_totp_secret(), version=2)
    assert local_portal.get("/explore").headers["location"].startswith("/auth/login")


# --- Command line -------------------------------------------------------------------------

def test_cli_creates_a_totp_account_only_with_a_working_code(folders, monkeypatch, capsys):
    monkeypatch.setattr(identity, "new_totp_secret", lambda: SECRET)
    monkeypatch.setattr("builtins.input", lambda prompt="": "000000" if now_code() != "000000" else "111111")
    assert cli.main(["local-account", "add", "ana.totp", "--totp", "--generate"]) == 2
    assert access.read_totp_accounts() == {}  # three wrong codes: nothing saved
    monkeypatch.setattr("builtins.input", lambda prompt="": now_code())
    assert cli.main(["local-account", "add", "ana.totp", "--totp", "--generate", "--roles", "Ventas"]) == 0
    out = capsys.readouterr().out
    assert " ".join(SECRET[i:i + 4] for i in range(0, 32, 4)) in out  # the key, beside the QR, shown once
    account = access.read_totp_accounts()["ana.totp"]
    assert account["totp"] == SECRET and account["roles"] == ("Ventas",)
    assert access.read_local_accounts() == {}
    assert cli.main(["local-account", "add", "ana.totp"]) == 1  # one name, one account
    other = identity.new_totp_secret()
    monkeypatch.setattr(identity, "new_totp_secret", lambda: other)
    monkeypatch.setattr("builtins.input", lambda prompt="": now_code(other))
    assert cli.main(["local-account", "totp", "ana.totp"]) == 0
    account = access.read_totp_accounts()["ana.totp"]
    assert account["totp"] == other and account["version"] == 2
    assert cli.main(["local-account", "roles", "ana.totp", "Sofibot.Admin"]) == 0
    assert access.read_totp_accounts()["ana.totp"]["roles"] == ("Sofibot.Admin",)
    assert cli.main(["local-account"]) == 0
    listing = capsys.readouterr().out
    assert "cuentas-totp.json" in listing and "ana.totp" in listing and other not in listing
    assert cli.main(["local-account", "remove", "ana.totp"]) == 0
    assert access.read_totp_accounts() == {}


def test_cli_totp_needs_a_totp_account(folders):
    add_account("solo.clave")
    assert cli.main(["local-account", "totp", "solo.clave"]) == 1


# --- From the portal (SOFIBOT_LOCAL_ACCOUNTS_WEB=1): temporary password, activated by its owner ----

@pytest.fixture
def web(local_portal, monkeypatch):
    monkeypatch.setenv("SOFIBOT_LOCAL_ACCOUNTS_WEB", "1")
    local_sign_in(local_portal)  # sofibot.admin: full access
    return local_portal


def admin_form(client, path="/admin/cuentas"):
    return csrf(client.get(path).text)


def temporary_password(page):
    return page.split('<code class="once">', 1)[1].split("</code>", 1)[0]


def shown_key(page):
    import re

    return re.search(r"clave secreta\s*<code>([A-Z2-7 ]+)</code>", page).group(1).replace(" ", "")


def create(client, name="gabri", **form):
    response = client.post("/admin/cuentas/nueva", data={"csrf": admin_form(client), "usuario": name,
                                                         "acceso": "total", **form})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store", response.text[:300]
    return temporary_password(response.text)


def new_browser():
    from fastapi.testclient import TestClient
    from sofibot_eqz.server import app

    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def activate(client, name, temporary, password="mi-contraseña-nueva", code=None, repeat=None):
    """Sign in with the temporary password and fill in the activation page; returns (response, secret)."""
    assert local_sign_in(client, name, password=temporary).headers["location"] == "/auth/activar"
    page = client.get("/auth/activar")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    secret = shown_key(page.text)
    response = client.post("/auth/activar", data={"csrf": csrf(page.text), "contrasena": password,
                                                  "repetir": password if repeat is None else repeat,
                                                  "codigo": now_code(secret) if code is None else code})
    return response, secret


def test_portal_creates_an_account_its_owner_activates(web):
    page = web.get("/admin/cuentas").text
    assert "Nueva cuenta con TOTP" in page and "acceso total" in page and "<svg" not in page
    temporary = create(web, nombre="Gabriel")
    account = access.read_totp_accounts()["gabri"]
    assert account["totp"] is None and access.pending(account) and identity.full_access(account["roles"])
    assert "pendiente de activar" in web.get("/admin/cuentas").text
    assert "gabri" in web.get("/admin").text  # in the record of administration changes

    owner = new_browser()
    assert local_sign_in(owner, "gabri", password=temporary).headers["location"] == "/auth/activar"
    assert owner.get("/explore").status_code == 302  # nothing else until it is activated
    page = owner.get("/auth/activar").text
    assert "<svg" in page and "Activa tu cuenta" in page  # the QR code: only its owner sees it
    # "Generar contraseña": made in the browser, never sent by the server
    assert "Generar contraseña" in page and "crypto.getRandomValues" in page and 'id="valor"></code>' in page
    response, secret = activate(owner, "gabri", temporary)
    assert response.status_code == 303 and response.headers["location"] == "/explore"
    assert owner.get("/explore").status_code == 200
    account = access.read_totp_accounts()["gabri"]
    assert account["totp"] == secret and not access.pending(account) and account["version"] == 2
    assert "activada" in web.get("/admin/cuentas").text

    later = new_browser()  # from now on: its own password, then the code (not the one just used)
    assert local_sign_in(later, "gabri", password=temporary).headers["location"].endswith("error=1")
    assert local_sign_in(later, "gabri", password="mi-contraseña-nueva").headers["location"] == "/auth/codigo"
    used = auth._used_steps["gabri"]  # the step of the code typed to activate it
    assert send_code(later, identity.totp_code(secret, used)).headers["location"].endswith("error=1")
    assert send_code(later, identity.totp_code(secret, used + 1)).headers["location"] == "/explore"


def test_activation_checks_password_and_code(web):
    temporary = create(web, acceso="roles", roles=["Sofibot.Consultas", "Ventas"])
    assert access.read_totp_accounts()["gabri"]["roles"] == ("Sofibot.Consultas", "Ventas")
    owner = new_browser()
    for kwargs, error in (({"password": "corta"}, "5"), ({"repeat": "otra-contraseña-larga"}, "6"),
                          ({"password": temporary}, "7"), ({"code": "abcdef"}, "1")):
        response, _ = activate(owner, "gabri", temporary, **kwargs)
        assert response.headers["location"].endswith(f"error={error}"), kwargs
    assert access.pending(access.read_totp_accounts()["gabri"])


def test_pending_accounts_get_no_session_or_token(web, monkeypatch):
    create(web)
    account = access.load_local_accounts()["gabri"]
    assert auth.local_account({"email": "gabri", "v": 1, "local": True}) is None
    monkeypatch.setenv("SOFIBOT_LOCAL_SECRET", "s" * 40)
    token = identity.issue_token("gabri", account, 5)
    with pytest.raises(identity.IdentityError):
        identity.from_local_token(token)


def test_temporary_password_expires(web, monkeypatch):
    monkeypatch.setenv("SOFIBOT_LOCAL_ACTIVATION_DAYS", "1")
    assert access.activation_days() == 1
    temporary = create(web)
    accounts = {n: dict(a) for n, a in access.read_totp_accounts().items()}
    from datetime import datetime, timedelta, timezone

    accounts["gabri"]["activar_hasta"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    access.save_totp_accounts(accounts)
    assert "caducada" in web.get("/admin/cuentas").text
    assert local_sign_in(new_browser(), "gabri", password=temporary).headers["location"].endswith("error=4")


def test_reset_gives_a_new_temporary_password_and_ends_sessions(web):
    temporary = create(web)
    owner = new_browser()
    activate(owner, "gabri", temporary)
    assert owner.get("/explore").status_code == 200
    response = web.post("/admin/cuentas/restablecer", data={"csrf": admin_form(web), "usuario": "gabri"})
    second = temporary_password(response.text)
    account = access.read_totp_accounts()["gabri"]
    assert access.pending(account) and account["totp"] is None and account["version"] == 3
    assert owner.get("/explore").headers["location"].startswith("/auth/login")  # phone lost: old session ends
    response, secret = activate(owner, "gabri", second, password="otra-contraseña-más")
    assert response.headers["location"] == "/explore"
    token = admin_form(web)
    web.post("/admin/cuentas/borrar", data={"csrf": token, "usuario": "gabri"})  # without "confirmo"
    assert "gabri" in access.read_totp_accounts()
    web.post("/admin/cuentas/borrar", data={"csrf": token, "usuario": "gabri", "confirmo": "1"})
    assert access.read_totp_accounts() == {}


def test_portal_never_touches_password_accounts_or_duplicates(web):
    token = admin_form(web)
    response = web.post("/admin/cuentas/nueva", data={"csrf": token, "usuario": "sofibot.admin", "acceso": "total"})
    assert response.status_code == 303 and "ya%20existe" in response.headers["location"]
    for path in ("/admin/cuentas/restablecer", "/admin/cuentas/borrar"):
        web.post(path, data={"csrf": token, "usuario": "sofibot.admin", "confirmo": "1"})
    assert "sofibot.admin" in access.read_local_accounts()
    assert web.post("/admin/cuentas/nueva", data={"csrf": "otro", "usuario": "x1"}).status_code == 403


def test_cli_activates_a_pending_account_directly(web, monkeypatch, capsys):
    create(web)
    assert cli.main(["local-account"]) == 0
    assert "pending activation" in capsys.readouterr().out
    other = identity.new_totp_secret()
    monkeypatch.setattr(identity, "new_totp_secret", lambda: other)
    monkeypatch.setattr("builtins.input", lambda prompt="": now_code(other))
    assert cli.main(["local-account", "totp", "gabri"]) == 0
    account = access.read_totp_accounts()["gabri"]
    assert account["totp"] == other and not access.pending(account)


def test_portal_creation_is_off_by_default(local_portal):
    local_sign_in(local_portal)
    page = local_portal.get("/admin/cuentas").text
    assert "Nueva cuenta con TOTP" not in page and "SOFIBOT_LOCAL_ACCOUNTS_WEB" in page
    response = local_portal.post("/admin/cuentas/nueva", data={"csrf": csrf(local_portal.get("/admin/usuarios").text),
                                                               "usuario": "gabri", "acceso": "total"})
    assert response.status_code == 404 and access.read_totp_accounts() == {}


def test_only_administrators_manage_accounts(web):
    add_account("tienda", roles=["Ventas"])
    web.get("/auth/logout")
    local_sign_in(web, "tienda")
    assert web.get("/admin/cuentas").status_code == 403

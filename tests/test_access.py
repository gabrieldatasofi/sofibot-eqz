"""Portal sign-in (auth.py) and per-report permissions (access.py), without Entra ID or a database."""
import json

import pytest
from fastapi.testclient import TestClient

from sofibot_eqz import access, auth, cli

TENANT, CLIENT = "tenant-id", "client-id"
ENTRA = {"SOFIBOT_AUTH": "entra", "ENTRA_TENANT_ID": TENANT, "ENTRA_CLIENT_ID": CLIENT,
         "ENTRA_CLIENT_SECRET": "secret", "SOFIBOT_PUBLIC_URL": "https://informes.test"}


TABLES = {"ventas": ["gold.ventas"], "finanzas": ["gold.ventas", "gold.costes"]}


def built_report(root, slug):
    folder = root / "output" / slug
    (folder / "assets").mkdir(parents=True)
    (folder / "report.json").write_text(json.dumps({"slug": slug, "name": slug.title(), "tables": TABLES[slug]}))
    (folder / "index.html").write_text(f"<h1>{slug}</h1>")
    (folder / "assets" / "logo.txt").write_text("logo")


def project(root, slug):
    folder = root / "reports" / slug
    folder.mkdir()
    (folder / "report.json").write_text(json.dumps({"slug": slug, "name": slug, "tables": TABLES[slug]}))
    (folder / "generate.py").write_text("")


def write_permissions(root, roles):
    (root / "reports" / "permisos.json").write_text(json.dumps({"roles": roles}))


class FakeEntra:
    """Stands in for msal.ConfidentialClientApplication."""

    def __init__(self, claims=None, error=None):
        self.claims, self.error = claims, error

    def initiate_auth_code_flow(self, scopes, redirect_uri):
        assert redirect_uri == "https://informes.test/auth/callback"
        return {"state": "s1", "nonce": "n1", "code_verifier": "v1", "auth_uri": "https://login.test/authorize?state=s1"}

    def acquire_token_by_auth_code_flow(self, flow, response):
        if response.get("state") != flow["state"]:
            raise ValueError("state mismatch")
        if self.error:
            return {"error": self.error}
        return {"id_token_claims": self.claims}


@pytest.fixture
def portal(folders, monkeypatch):
    for name in ("SOFIBOT_AUTH", "SOFIBOT_VIEWER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    built_report(folders, "ventas")
    built_report(folders, "finanzas")
    from sofibot_eqz.server import app

    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def sign_in(client, monkeypatch, roles, tenant=TENANT, error=None):
    claims = {"tid": tenant, "aud": CLIENT, "name": "Ana Pérez", "preferred_username": "ana@empresa.test", "roles": roles}
    monkeypatch.setattr(auth, "_client", lambda settings: FakeEntra(claims, error))
    response = client.get("/auth/login", params={"next": "/output/ventas/"})
    assert response.status_code == 302 and response.headers["location"].startswith("https://login.test/")
    return client.get("/auth/callback", params={"code": "c1", "state": "s1"})


@pytest.fixture
def entra(portal, monkeypatch):
    for name, value in ENTRA.items():
        monkeypatch.setenv(name, value)
    return portal


# --- access.py -------------------------------------------------------------------------

def test_a_report_needs_all_its_tables():
    permissions = {"Ventas": {"gold.ventas"}, "Costes": {"gold.costes"}, "Direccion": {"*"}}
    assert access.visible({"roles": ["Ventas"]}, TABLES["ventas"], permissions)
    assert not access.visible({"roles": ["Ventas"]}, TABLES["finanzas"], permissions)  # lacks gold.costes
    assert access.visible({"roles": ["Ventas", "Costes"]}, TABLES["finanzas"], permissions)  # roles add up
    assert access.visible({"roles": ["Otro", "Direccion"]}, TABLES["finanzas"], permissions)
    assert not access.visible({"roles": []}, TABLES["ventas"], permissions)
    assert not access.visible({"roles": ["Ventas"]}, [], permissions)  # unknown tables: only "*"
    assert access.visible({"roles": ["Direccion"]}, [], permissions)
    assert access.visible(None, TABLES["finanzas"], {})  # no per-user sign-in: everything


def test_permissions_file_is_case_insensitive_for_tables(folders):
    write_permissions(folders, {"Ventas": ["GOLD.Ventas"], "Direccion": ["*"]})
    assert access.read() == {"Ventas": {"gold.ventas"}, "Direccion": {"*"}}


@pytest.mark.parametrize("content", [None, "not json", '{"roles": ["ventas"]}', '{"roles": {"Ventas": "gold.ventas"}}',
                                     '{"roles": {"Ventas": ["ventas"]}}', '{"roles": {"Ventas": ["dbo.ventas"]}}'])
def test_missing_or_malformed_permissions_deny_everything(folders, content):
    if content is not None:
        (folders / "reports" / "permisos.json").write_text(content)
    with pytest.raises(access.PermissionsError):
        access.read()
    assert access.load() == {}
    assert not access.visible({"roles": ["Ventas"]}, TABLES["ventas"])


# --- auth.py settings ------------------------------------------------------------------

def test_sign_in_mode_defaults_and_validation():
    assert auth.mode({}) == "none"
    assert auth.mode({"SOFIBOT_VIEWER_PASSWORD": "x"}) == "basic"
    assert auth.check_settings(ENTRA) == "entra"
    with pytest.raises(RuntimeError, match="SOFIBOT_AUTH must be"):
        auth.mode({"SOFIBOT_AUTH": "ldap"})
    with pytest.raises(RuntimeError, match="SOFIBOT_VIEWER_PASSWORD"):
        auth.check_settings({"SOFIBOT_AUTH": "basic"})
    with pytest.raises(RuntimeError, match="ENTRA_CLIENT_SECRET"):
        auth.check_settings({**ENTRA, "ENTRA_CLIENT_SECRET": ""})
    with pytest.raises(RuntimeError, match="https"):
        auth.check_settings({**ENTRA, "SOFIBOT_PUBLIC_URL": "http://informes.test"})


@pytest.mark.parametrize("value, expected", [
    ("/output/ventas/?x=1", "/output/ventas/?x=1"), (None, "/explore"), ("https://evil.test", "/explore"),
    ("//evil.test", "/explore"), ("/\\evil.test", "/explore"), ("/a\r\nb", "/explore"),
])
def test_only_local_paths_after_sign_in(value, expected):
    assert auth.safe_next(value) == expected


# --- portal: open and shared password --------------------------------------------------

def test_open_portal_serves_every_report(portal):
    page = portal.get("/dashboard").text
    assert "/output/ventas/" in page and "/output/finanzas/" in page and "Cerrar sesión" not in page
    assert portal.get("/output/ventas/").text == "<h1>ventas</h1>"
    assert portal.get("/output/ventas/assets/logo.txt").text == "logo"
    assert portal.get("/output/ventas").headers["location"] == "/output/ventas/"
    assert portal.get("/output/ventas/no-existe.html").status_code == 404


@pytest.mark.parametrize("path", ["/output/ventas/%2E%2E/finanzas/index.html", "/output/ventas/..%2Ffinanzas/index.html",
                                  "/output/.ventas-previous/index.html"])
def test_a_report_path_cannot_reach_another_folder(portal, path):
    assert portal.get(path).status_code == 404


def test_shared_password(portal, monkeypatch):
    monkeypatch.setenv("SOFIBOT_VIEWER_PASSWORD", "clave")
    assert portal.get("/dashboard").status_code == 401
    assert portal.get("/output/ventas/").status_code == 401
    assert portal.get("/dashboard", auth=("equivalenza", "clave")).status_code == 200
    assert portal.get("/health").status_code == 200


# --- portal: Entra ID ------------------------------------------------------------------

def test_entra_requires_sign_in(entra):
    response = entra.get("/output/ventas/?vista=1")
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/output/ventas/%3Fvista%3D1"
    assert entra.get("/api/reports").status_code == 401
    assert entra.get("/health").status_code == 200


def test_entra_user_sees_only_their_reports(entra, folders, monkeypatch):
    write_permissions(folders, {"Ventas": ["gold.ventas"]})
    response = sign_in(entra, monkeypatch, ["Ventas"])
    assert response.status_code == 302 and response.headers["location"] == "/output/ventas/"
    page = entra.get("/dashboard").text
    assert "Ana Pérez" in page and "/output/ventas/" in page and "/output/finanzas/" not in page
    assert entra.get("/output/ventas/").status_code == 200
    assert entra.get("/output/finanzas/").status_code == 403
    assert entra.get("/output/finanzas/assets/logo.txt").status_code == 403
    listing = entra.get("/api/reports").json()
    assert [report["slug"] for report in listing["reports"]] == ["ventas"] and listing["projects"] == ["ventas"]


def test_entra_permissions_change_without_restart(entra, folders, monkeypatch):
    write_permissions(folders, {"Ventas": ["gold.ventas"]})
    sign_in(entra, monkeypatch, ["Ventas"])
    assert entra.get("/output/finanzas/").status_code == 403
    write_permissions(folders, {"Ventas": ["*"]})
    assert entra.get("/output/finanzas/").status_code == 200


def test_entra_user_without_roles_sees_nothing(entra, folders, monkeypatch):
    write_permissions(folders, {"Ventas": ["*"]})
    sign_in(entra, monkeypatch, [])
    assert "No tienes acceso" in entra.get("/dashboard").text
    assert entra.get("/output/ventas/").status_code == 403


@pytest.mark.parametrize("kwargs", [{"tenant": "otro-tenant"}, {"error": "invalid_grant"}])
def test_entra_rejected_sign_in_creates_no_session(entra, folders, monkeypatch, kwargs):
    write_permissions(folders, {"Ventas": ["*"]})
    assert sign_in(entra, monkeypatch, ["Ventas"], **kwargs).status_code == 401
    assert entra.get("/dashboard").status_code == 302


def test_entra_forged_state_is_rejected(entra, monkeypatch):
    monkeypatch.setattr(auth, "_client", lambda settings: FakeEntra({"tid": TENANT, "aud": CLIENT}))
    entra.get("/auth/login")
    assert entra.get("/auth/callback", params={"code": "c1", "state": "otro"}).status_code == 401
    assert entra.get("/dashboard").status_code == 302


def test_entra_logout(entra, folders, monkeypatch):
    write_permissions(folders, {"Ventas": ["*"]})
    sign_in(entra, monkeypatch, ["Ventas"])
    assert entra.get("/dashboard").status_code == 200
    assert entra.get("/auth/logout").status_code == 200
    assert entra.get("/dashboard").status_code == 302


# --- sofibot permissions ---------------------------------------------------------------

def test_entra_report_needs_every_table_across_roles(entra, folders, monkeypatch):
    write_permissions(folders, {"Ventas": ["gold.ventas"], "Costes": ["gold.costes"]})
    sign_in(entra, monkeypatch, ["Ventas", "Costes"])
    assert entra.get("/output/finanzas/").status_code == 200


def test_permissions_command(folders, capsys):
    project(folders, "ventas")
    project(folders, "finanzas")
    (folders / "reports" / "gold_schema.json").write_text(json.dumps({"tables": {"gold.ventas": {}, "gold.costes": {}}}))
    write_permissions(folders, {"Ventas": ["gold.ventas", "gold.compras"]})
    assert cli.main(["permissions"]) == 0
    out, err = capsys.readouterr()
    assert "Ventas" in out and "reports: ventas" in out
    assert "'gold.compras', which is not in gold_schema.json" in err
    assert "no role can see 'finanzas': its tables gold.costes are in no role" in err
    (folders / "reports" / "permisos.json").write_text("{}")
    assert cli.main(["permissions"]) == 1

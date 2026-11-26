"""Portal pages (pages.py, admin.py): landing, explore, reports, queries, connect, administration."""
import io
import json
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from sofibot_eqz import auth, config, drafts, identity, pages
from test_access import ENTRA, built_report, sign_in

CONTRACT = {"schema": "gold", "generated_at": "2026-11-01T00:00:00+00:00", "tables": {
    "gold.ventas": {"type": "table", "description": "Ventas", "columns": [{"name": "mes"}, {"name": "importe"}]},
    "gold.costes": {"type": "table", "description": "", "columns": [{"name": "mes"}]}}}


@pytest.fixture
def portal(folders, monkeypatch):
    for name, value in ENTRA.items():
        monkeypatch.setenv(name, value)
    for name in ("SOFIBOT_QUERY_URL", "SOFIBOT_CODE_API", "SOFIBOT_API_TOKEN", "SQLSERVER_HOST"):
        monkeypatch.delenv(name, raising=False)
    (folders / "reports" / "gold_schema.json").write_text(json.dumps(CONTRACT))
    (folders / "reports" / "permisos.json").write_text(json.dumps({"roles": {"Ventas": ["gold.ventas"]}}))
    built_report(folders, "ventas")
    from sofibot_eqz.server import app

    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_landing_then_explore(portal, monkeypatch):
    landing = portal.get("/")
    assert landing.status_code == 200 and "Iniciar sesión con Microsoft" in landing.text
    assert portal.get("/explore").status_code == 302          # everything else needs sign-in
    sign_in(portal, monkeypatch, ["Ventas"])
    assert portal.get("/").headers["location"] == "/explore"
    page = portal.get("/explore").text
    assert "Ver informes (1)" in page and "rol de consultas" in page.replace("no está activado", "rol de consultas")
    assert "Administración" not in page and "Revisión" not in page


def test_open_portal_goes_straight_to_explore(portal, monkeypatch):
    monkeypatch.setenv("SOFIBOT_AUTH", "none")
    assert portal.get("/").headers["location"] == "/explore"
    assert portal.get("/explore").status_code == 200


def test_reports_mark_mine_and_list_my_drafts(portal, folders, monkeypatch):
    monkeypatch.setenv("SOFIBOT_CODE_API", "entra")
    (folders / "reports" / "ventas").mkdir()
    (folders / "reports" / "ventas" / "report.json").write_text(json.dumps({"slug": "ventas", "name": "V", "tables": ["gold.ventas"]}))
    (folders / "reports" / "ventas" / "generate.py").write_text('T = "gold.ventas"\n')
    drafts.create_draft("ventas", from_report=True, actor="ana@empresa.test")
    sign_in(portal, monkeypatch, ["Ventas", identity.ROLE_AUTHOR])
    page = portal.get("/informes").text
    assert 'tag mine">Mío' in page and "Mis borradores" in page and "En edición" in page
    assert portal.get("/dashboard").status_code == 200


def test_queries_page_forwards_with_the_users_token(portal, monkeypatch):
    monkeypatch.setenv("SOFIBOT_QUERY_URL", "http://consultas:8080")
    calls = []

    def fake(method, route, token, payload=None):
        calls.append((method, route, token, payload))
        if route == "/catalog":
            return 200, {"tables": {"gold.ventas": {"description": "Ventas", "has_period": True, "rules": [],
                                                     "dimensions": {"mes": {"description": ""}},
                                                     "measures": {"importe": {"format": "eur", "description": ""}}}}}
        return 200, {"table": "gold.ventas", "columns": ["mes", "importe"], "truncated": False,
                     "period": {"from": "2026-01", "to": "2026-02"},
                     "rows": [["2026-01-01", 1234.5], ["2026-02-01", None]]}

    monkeypatch.setattr(pages, "call_query_service", fake)
    sign_in(portal, monkeypatch, ["Ventas"])
    assert "rol de consultas" in portal.get("/consultas").text
    portal.cookies.clear()
    sign_in(portal, monkeypatch, ["Ventas", identity.ROLE_QUERY])
    assert "ha caducado" in portal.get("/consultas").text     # the fake sign-in returns no API token
    monkeypatch.setattr(auth, "api_token", lambda request: "user-token")
    page = portal.get("/consultas", params={"tabla": "gold.ventas", "m": "importe", "d": "mes",
                                            "desde": "2026-01", "hasta": "2026-02", "run": "1"}).text
    assert "1.234,50 €" in page and "ene 2026" in page and "Sin datos" in page
    method, route, token, payload = calls[-1]
    assert (method, route, token) == ("POST", "", "user-token")
    assert payload == {"table": "gold.ventas", "measures": ["importe"], "dimensions": ["mes"],
                       "period": {"from": "2026-01", "to": "2026-02"}}


def test_api_token_is_kept_in_memory_not_in_the_cookie():
    class Fake:
        session = {}

    request = Fake()
    auth.keep_api_token(request, {"access_token": "secret-token", "expires_in": 3600})
    assert "secret-token" not in json.dumps(request.session)
    assert auth.api_token(request) == "secret-token"
    auth.forget_api_token(request)
    assert auth.api_token(request) is None


def test_connect_page_and_download(portal, monkeypatch, folders):
    monkeypatch.setenv("SOFIBOT_CODE_API", "entra")
    monkeypatch.setattr(config, "MCP_DIR", folders / "mcp")
    (folders / "mcp").mkdir()
    for name in pages.MCP_FILES:
        (folders / "mcp" / name).write_text(name)
    sign_in(portal, monkeypatch, [identity.ROLE_AUTHOR])
    page = portal.get("/conectar").text
    assert "sofibot_informes_mcp.py" in page and "tenant-id" in page and "mcp_servers.sofibot_informes" in page
    assert "Necesitas el rol" not in page.split('id="consultas"')[0]
    archive = zipfile.ZipFile(io.BytesIO(portal.get("/descargas/sofibot-mcp.zip").content))
    assert sorted(archive.namelist()) == sorted(f"sofibot-mcp/{n}" for n in pages.MCP_FILES)


def test_connect_page_offers_the_exe_when_built(portal, monkeypatch, folders):
    monkeypatch.setenv("SOFIBOT_CODE_API", "entra")
    monkeypatch.setattr(config, "MCP_DIR", folders / "mcp")
    sign_in(portal, monkeypatch, [identity.ROLE_AUTHOR])
    assert portal.get("/descargas/sofibot-mcp.exe").status_code == 404
    assert "Python 3.12" in portal.get("/conectar").text
    (folders / "mcp" / "dist").mkdir(parents=True)
    (folders / "mcp" / "dist" / "sofibot-mcp.exe").write_bytes(b"MZ fake")
    page = portal.get("/conectar").text
    assert "Descargar el conector de Sofibot" in page and "sofibot-mcp.exe informes" in page
    assert "args = [&#x27;informes&#x27;]" in page and "Claude Desktop" in page
    assert portal.get("/descargas/sofibot-mcp.exe").content == b"MZ fake"
    archive = zipfile.ZipFile(io.BytesIO(portal.get("/descargas/sofibot-conectar.zip").content))
    settings = json.loads(archive.read("sofibot-conectar/sofibot-conexion.json"))
    assert archive.read("sofibot-conectar/sofibot-mcp.exe") == b"MZ fake"
    assert settings["tenant_id"] == "tenant-id" and settings["informes"] is True and "secret" not in json.dumps(settings)


def test_connection_file_is_public_and_has_no_secret(portal):
    settings = portal.get("/conexion.json").json()   # no sign-in needed
    assert settings["client_id"] == "client-id" and settings["url"] == "https://informes.test"
    assert "secret" not in json.dumps(settings).lower()


# --- Administration --------------------------------------------------------------------

@pytest.fixture
def admin(portal, monkeypatch, folders):
    class Keys:
        def get_signing_keys(self):
            return [1, 2]

    monkeypatch.setattr(identity, "_jwks", lambda tenant: Keys())
    monkeypatch.setattr(config, "DOCS_DIR", folders / "docs")
    (folders / "docs").mkdir()
    (folders / "docs" / "12-arquitectura.md").write_text(
        "# Arquitectura\n\n## Partes\n\nVer [seguridad](06-seguridad.md#datos) y [ejemplo](../examples/x.py).\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    sign_in(portal, monkeypatch, [identity.ROLE_ADMIN])
    return portal


def csrf(text):
    return re.search(r'name="csrf" value="([^"]+)"', text).group(1)


def test_admin_needs_the_role(portal, monkeypatch):
    sign_in(portal, monkeypatch, ["Ventas"])
    assert portal.get("/admin").status_code == 403 and portal.get("/admin/permisos").status_code == 403


def test_admin_status(admin):
    page = admin.get("/admin").text
    for text in ("SQL Server y tablas Gold", "Missing settings", "Microsoft Entra ID", "Accesibles (2)",
                 "gold.ventas", "Funcionalidad 1", "Funcionalidad 2", "No configurado"):
        assert text in page, text
    assert "secret" not in page  # the client secret is never shown


def test_admin_edits_permissions(admin, folders):
    form = admin.get("/admin/permisos")
    assert "Ventas" in form.text and "Informes que ve" in form.text
    data = {"csrf": csrf(form.text), "count": "2", "role0": "Ventas", "tables0": ["gold.ventas", "gold.costes"],
            "role1": "Direccion", "tables1": ["*", "gold.ventas"]}
    assert admin.post("/admin/permisos", data=data).status_code == 303
    saved = json.loads((folders / "acceso" / "permisos.json").read_text())     # moves to acceso/
    assert saved == {"roles": {"Ventas": ["gold.costes", "gold.ventas"], "Direccion": ["*"]}}
    assert "reports/permisos.json" not in admin.get("/admin/permisos").text      # no "older installation" notice
    assert admin.post("/admin/permisos", data=data).status_code == 303
    assert list((folders / "acceso" / ".copias").glob("permisos-*.json"))       # previous file kept
    bad = admin.post("/admin/permisos", data={**data, "role1": "Con espacios"})
    assert "No se ha guardado" in admin.get(bad.headers["location"]).text
    assert admin.post("/admin/permisos", data={**data, "csrf": "forged"}).status_code == 403
    deleted = admin.post("/admin/permisos", data={**data, "delete1": "1"})
    assert deleted.status_code == 303
    assert list(json.loads((folders / "acceso" / "permisos.json").read_text())["roles"]) == ["Ventas"]
    function_role = admin.post("/admin/permisos", data={**data, "role1": identity.ROLE_AUTHOR})
    assert "rol de funcionalidad" in admin.get(function_role.headers["location"]).text


def test_admin_documentation(admin):
    assert "Arquitectura" in admin.get("/admin/docs").text
    page = admin.get("/admin/docs/12-arquitectura.md").text
    assert 'href="/admin/docs/06-seguridad.md#datos"' in page and "<table>" in page
    assert "../examples" not in page
    assert admin.get("/admin/docs/..%2F..%2Fsecret.md").status_code in (403, 404)


def test_admin_edits_users(admin, folders):
    form = admin.get("/admin/usuarios")
    assert form.status_code == 200 and "ana@empresa.test" in form.text and "Ventas" in form.text
    data = {"csrf": csrf(form.text), "count": "2", "email0": "ana@empresa.test", "roles0": [identity.ROLE_ADMIN],
            "email1": " Luis@Empresa.test ", "roles1": [identity.ROLE_QUERY, "Ventas"]}
    assert admin.post("/admin/usuarios", data=data).status_code == 303
    saved = json.loads((folders / "acceso" / "usuarios.json").read_text())
    assert saved == {"usuarios": {"ana@empresa.test": [identity.ROLE_ADMIN],
                                  "luis@empresa.test": [identity.ROLE_QUERY, "Ventas"]}}
    assert "luis@empresa.test" in admin.get("/admin/usuarios").text and "ventas" in admin.get("/admin/usuarios").text
    bad = admin.post("/admin/usuarios", data={**data, "email1": "no es un correo"})
    assert "Correo no válido" in admin.get(bad.headers["location"]).text
    assert admin.post("/admin/usuarios", data={**data, "csrf": "forged"}).status_code == 403
    deleted = admin.post("/admin/usuarios", data={**data, "delete1": "1"})
    assert deleted.status_code == 303 and list(json.loads((folders / "acceso" / "usuarios.json").read_text())["usuarios"]) == ["ana@empresa.test"]
    assert list((folders / "acceso" / ".copias").glob("usuarios-*.json"))


def test_admin_cannot_remove_their_own_admin_role(admin, folders):
    form = admin.get("/admin/usuarios")
    for data in ({"email0": "ana@empresa.test", "roles0": ["Ventas"]}, {"email0": "ana@empresa.test", "delete0": "1"}):
        response = admin.post("/admin/usuarios", data={"csrf": csrf(form.text), "count": "1", **data})
        assert "No puedes quitarte" in admin.get(response.headers["location"]).text
    assert admin.get("/admin").status_code == 200


def test_a_role_change_applies_without_signing_in_again(admin, folders):
    from conftest import grant

    grant("ana@empresa.test", ["Ventas"])
    assert admin.get("/admin").status_code == 403

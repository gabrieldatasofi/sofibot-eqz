import json

import pytest
from fastapi.testclient import TestClient

from sofibot_eqz import cli, drafts

API_TOKEN = "a" * 40
ADMIN_TOKEN = "b" * 40
CONTRACT = {"source": "SQL Server", "schema": "gold", "note": "Structure only.",
            "tables": {"gold.month_store": {"type": "table", "description": "", "columns": []},
                       "gold.products": {"type": "view", "description": "", "columns": []}}}
GOOD_CODE = 'TABLE = "gold.month_store"\nSQL = f"SELECT 1 FROM {TABLE}"\n'


@pytest.fixture
def contract(folders):
    (folders / "reports" / "gold_schema.json").write_text(json.dumps(CONTRACT), encoding="utf-8")
    return folders


def published(root, slug="ventas", code=GOOD_CODE):
    project = root / "reports" / slug
    project.mkdir()
    (project / "report.json").write_text(json.dumps({"slug": slug, "name": "Ventas", "tables": ["gold.month_store"]}))
    (project / "generate.py").write_text(code)
    return project


# --- drafts.py -------------------------------------------------------------------------

def test_describe_schema_adds_the_guide_and_needs_the_contract(folders):
    with pytest.raises(drafts.DraftError) as error:
        drafts.describe_schema()
    assert error.value.status == 503
    (folders / "reports" / "gold_schema.json").write_text(json.dumps(CONTRACT), encoding="utf-8")
    schema = drafts.describe_schema()
    assert set(schema["tables"]) == set(CONTRACT["tables"]) and "check_draft" in schema["report_guide"]


def test_new_draft_is_outside_the_published_reports(contract):
    from sofibot_eqz import projects

    draft = drafts.create_draft("ventas", "Ventas", "gold.month_store")
    assert draft["status"] == "draft" and draft["files"] == ["generate.py", "report.json"]
    assert (contract / "reports" / ".borradores" / "ventas" / "generate.py").is_file()
    assert projects.projects() == {}  # never built, not in the portal
    assert drafts.check_draft("ventas")["ok"]


@pytest.mark.parametrize("slug, name, table", [("Ventas", "x", "gold.month_store"), ("../x", "x", "gold.month_store"),
                                               ("ventas", "", "gold.month_store"), ("ventas", "x", "gold.unknown")])
def test_new_draft_validates_input(contract, slug, name, table):
    with pytest.raises(drafts.DraftError):
        drafts.create_draft(slug, name, table)


def test_draft_of_a_published_report_copies_its_code(contract):
    published(contract)
    with pytest.raises(drafts.DraftError) as error:
        drafts.create_draft("ventas", "Otro", "gold.month_store")
    assert error.value.status == 409
    drafts.create_draft("ventas", from_report=True)
    assert drafts.read_file("ventas", "generate.py")["content"] == GOOD_CODE


@pytest.mark.parametrize("name", ["../report.json", ".draft.json", "data.csv", "Generate.py", "sub/generate.py"])
def test_only_code_files_can_be_read_or_written(contract, name):
    drafts.create_draft("ventas", "Ventas", "gold.month_store")
    with pytest.raises(drafts.DraftError):
        drafts.write_file("ventas", name, "x")
    with pytest.raises(drafts.DraftError):
        drafts.read_file("ventas", name)


def test_report_json_must_keep_its_slug(contract):
    drafts.create_draft("ventas", "Ventas", "gold.month_store")
    for content in ("{", json.dumps({"slug": "otro", "name": "x"}), "[]"):
        with pytest.raises(drafts.DraftError):
            drafts.write_file("ventas", "report.json", content)


@pytest.mark.parametrize("code, tables, problem", [
    ("def broken(:\n", ["gold.month_store"], "syntax error"),
    ('SQL = "SELECT 1 FROM gold.products"\n', ["gold.month_store"], "does not list"),
    ('SQL = "SELECT 1 FROM gold.secret"\n', ["gold.month_store", "gold.secret"], "Not in the schema contract"),
])
def test_static_check_finds_problems_without_running_code(contract, code, tables, problem):
    drafts.create_draft("ventas", "Ventas", "gold.month_store")
    drafts.write_file("ventas", "report.json", json.dumps({"slug": "ventas", "name": "Ventas", "tables": tables}))
    drafts.write_file("ventas", "generate.py", code)
    checked = drafts.check_draft("ventas")
    assert not checked["ok"] and any(problem in item for item in checked["problems"])
    assert drafts.submit_draft("ventas")["submitted"] is False
    assert drafts.draft_status("ventas")["status"] == "draft"


def test_submit_publish_and_backup(contract):
    published(contract, code="OLD = 1\n")
    drafts.create_draft("ventas", from_report=True)
    drafts.write_file("ventas", "generate.py", GOOD_CODE)
    with pytest.raises(drafts.DraftError):  # not submitted yet
        drafts.publish("ventas")
    assert drafts.submit_draft("ventas")["submitted"]
    result = drafts.publish("ventas")
    assert (contract / "reports" / "ventas" / "generate.py").read_text() == GOOD_CODE
    assert (contract / "reports" / ".borradores" / ".anteriores").is_dir()
    assert result["previous_code"] and "OLD = 1" in open(result["previous_code"] + "/generate.py").read()
    assert drafts.draft_status("ventas")["status"] == "published"


def test_reject_keeps_the_comment_until_the_next_change(contract):
    drafts.create_draft("ventas", "Ventas", "gold.month_store")
    drafts.submit_draft("ventas")
    drafts.reject("ventas", "Usa meses completos")
    assert drafts.draft_status("ventas")["comment"] == "Usa meses completos"
    drafts.write_file("ventas", "generate.py", GOOD_CODE)
    status = drafts.draft_status("ventas")
    assert status["status"] == "draft" and "comment" not in status


def test_cli_publish_and_reject(contract, capsys):
    drafts.create_draft("ventas", "Ventas", "gold.month_store")
    assert cli.main(["publish", "ventas"]) == 1  # not submitted
    assert cli.main(["reject", "ventas", "--comment", "no"]) == 0
    assert cli.main(["publish", "ventas", "--force"]) == 0
    assert cli.main(["drafts"]) == 0 and "published" in capsys.readouterr().out


# --- API -------------------------------------------------------------------------------

@pytest.fixture
def api(contract, monkeypatch):
    for name in ("SOFIBOT_AUTH", "SOFIBOT_VIEWER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SOFIBOT_API_TOKEN", API_TOKEN)
    monkeypatch.setenv("SOFIBOT_ADMIN_TOKEN", ADMIN_TOKEN)
    from sofibot_eqz.server import app

    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_needs_its_own_token(api, monkeypatch):
    assert api.get("/api/code/schema").status_code == 401
    assert api.get("/api/code/schema", headers=bearer(ADMIN_TOKEN)).status_code == 401
    assert api.get("/api/admin/drafts", headers=bearer(API_TOKEN)).status_code == 401
    monkeypatch.setenv("SOFIBOT_API_TOKEN", ADMIN_TOKEN)  # same as the admin token: refused
    assert api.get("/api/code/schema", headers=bearer(ADMIN_TOKEN)).status_code == 503
    monkeypatch.delenv("SOFIBOT_API_TOKEN")
    assert api.get("/api/code/schema", headers=bearer(API_TOKEN)).status_code == 503


def test_api_ignores_the_portal_sign_in(api, monkeypatch):
    monkeypatch.setenv("SOFIBOT_VIEWER_PASSWORD", "clave")
    assert api.get("/api/reports").status_code == 401
    assert api.get("/api/code/schema", headers=bearer(API_TOKEN)).status_code == 200


def test_api_full_flow(api):
    headers = bearer(API_TOKEN)
    assert api.get("/api/code/schema", headers=headers).json()["tables"]
    created = api.post("/api/code/drafts", headers=headers,
                       json={"slug": "ventas", "name": "Ventas", "table": "gold.month_store"})
    assert created.status_code == 201
    assert api.post("/api/code/drafts", headers=headers, json={"slug": "ventas", "name": "x"}).status_code == 409
    assert api.put("/api/code/drafts/ventas/files/generate.py", headers=headers,
                   json={"content": GOOD_CODE}).json()["status"] == "draft"
    assert api.get("/api/code/drafts/ventas/files/generate.py", headers=headers).json()["content"] == GOOD_CODE
    assert api.get("/api/code/drafts/ventas/files/.draft.json", headers=headers).status_code == 400
    assert api.get("/api/code/drafts/nada", headers=headers).status_code == 404
    assert api.post("/api/code/drafts/ventas/check", headers=headers).json()["ok"]
    assert api.post("/api/code/drafts/ventas/submit", headers=headers).json()["submitted"]
    # The API token cannot publish; the administrator can.
    assert api.post("/api/admin/drafts/ventas/publish", headers=headers).status_code == 401
    assert api.get("/api/admin/drafts", headers=bearer(ADMIN_TOKEN)).json()["drafts"][0]["status"] == "submitted"
    assert api.post("/api/admin/drafts/ventas/publish", headers=bearer(ADMIN_TOKEN)).json()["status"] == "published"
    reports = api.get("/api/code/reports", headers=headers).json()["reports"]
    assert reports == [{"slug": "ventas", "name": "Ventas", "description": "Ventas", "tables": ["gold.month_store"],
                        "has_draft": True}]
    assert api.delete("/api/code/drafts/ventas", headers=headers).json() == {"deleted": "ventas"}


# --- Entra ID: authors and reviewers ---------------------------------------------------

PREVIEW_CODE = """import argparse, pathlib
TABLE = "gold.month_store"
p = argparse.ArgumentParser(); p.add_argument('--output', type=pathlib.Path)
out = p.parse_args().output; out.mkdir(parents=True, exist_ok=True)
(out / 'index.html').write_text('preview of ventas')
"""


def permissions(root, roles):
    (root / "reports" / "permisos.json").write_text(json.dumps({"roles": roles}))


@pytest.fixture
def entra_api(api, contract, monkeypatch, entra_token):
    monkeypatch.setenv("SOFIBOT_CODE_API", "entra")
    permissions(contract, {"Tiendas": ["gold.month_store"], "Direccion": ["*"]})
    return api


def test_entra_author_works_only_on_their_tables(entra_api, entra_token):
    author = {"Authorization": entra_token(["Sofibot.Autor", "Tiendas"], email="laura@eqz.test")}
    assert entra_api.get("/api/code/schema", headers={"Authorization": f"Bearer {API_TOKEN}"}).status_code == 401
    assert entra_api.get("/api/code/schema", headers={"Authorization": entra_token(["Tiendas"])}).status_code == 403
    assert list(entra_api.get("/api/code/schema", headers=author).json()["tables"]) == ["gold.month_store"]
    assert entra_api.post("/api/code/drafts", headers=author,
                          json={"slug": "productos", "name": "P", "table": "gold.products"}).status_code == 400
    assert entra_api.post("/api/code/drafts", headers=author,
                          json={"slug": "ventas", "name": "Ventas", "table": "gold.month_store"}).status_code == 201
    manifest = {"slug": "ventas", "name": "Ventas", "tables": ["gold.month_store", "gold.products"]}
    assert entra_api.put("/api/code/drafts/ventas/files/report.json", headers=author,
                         json={"content": json.dumps(manifest)}).status_code == 403
    assert entra_api.post("/api/code/drafts/ventas/submit", headers=author).json()["submitted"]
    history = entra_api.get("/api/code/drafts/ventas", headers=author).json()["history"]
    assert [(e["who"], e["operation"]) for e in history] == [("laura@eqz.test", "crear"), ("laura@eqz.test", "enviar")]
    # A draft over tables another author cannot use does not exist for them.
    drafts.create_draft("productos", "P", "gold.products", actor="otra@eqz.test")
    assert [d["slug"] for d in entra_api.get("/api/code/drafts", headers=author).json()["drafts"]] == ["ventas"]
    assert entra_api.get("/api/code/drafts/productos", headers=author).status_code == 404


@pytest.fixture
def review(contract, monkeypatch, entra_token):
    from test_access import ENTRA

    for name, value in ENTRA.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SOFIBOT_REVIEW_OWN", raising=False)
    permissions(contract, {"Tiendas": ["gold.month_store"]})
    drafts.create_draft("ventas", "Ventas", "gold.month_store", actor="laura@eqz.test")
    drafts.write_file("ventas", "generate.py", PREVIEW_CODE, actor="laura@eqz.test")
    assert drafts.submit_draft("ventas", actor="laura@eqz.test")["submitted"]
    from sofibot_eqz.server import app

    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def as_reviewer(client, monkeypatch, roles):
    """Signs in through the fake Entra ID of test_access: the reviewer is ana@empresa.test."""
    from test_access import sign_in

    sign_in(client, monkeypatch, roles)
    return client


def csrf(page):
    import re

    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def test_review_preview_and_publish(review, contract, monkeypatch):
    as_reviewer(review, monkeypatch, ["Sofibot.Revisor", "Tiendas"])
    assert "Ventas" in review.get("/revision").text
    page = review.get("/revision/ventas")
    assert page.status_code == 200 and "Generar vista previa" in page.text and "TABLE = " in page.text
    assert review.post("/revision/ventas/vista-previa", data={"csrf": "forged"}).status_code == 403
    assert review.post("/revision/ventas/vista-previa", data={"csrf": csrf(page)}).status_code == 303
    assert review.get("/revision/ventas/vista-previa/").text == "preview of ventas"
    assert not (contract / "output" / "ventas").exists()  # not in the portal yet
    response = review.post("/revision/ventas/publicar", data={"csrf": csrf(page)})
    assert response.status_code == 303 and "Publicado" in response.headers["location"]
    assert (contract / "output" / "ventas" / "index.html").read_text() == "preview of ventas"
    assert (contract / "reports" / "ventas" / "generate.py").read_text() == PREVIEW_CODE
    operations = [(e["who"], e["operation"]) for e in drafts.history("ventas")]
    assert operations[-2:] == [("ana@empresa.test", "vista previa"), ("ana@empresa.test", "publicar")]


def test_review_needs_role_and_tables(review, monkeypatch):
    as_reviewer(review, monkeypatch, ["Tiendas"])
    assert review.get("/revision").status_code == 403
    review.cookies.clear()
    as_reviewer(review, monkeypatch, ["Sofibot.Revisor"])
    assert "No hay borradores" in review.get("/revision").text
    assert review.get("/revision/ventas").status_code == 404


def test_reviewer_cannot_publish_own_submission(review, monkeypatch):
    drafts.write_file("ventas", "generate.py", PREVIEW_CODE, actor="ana@empresa.test")
    drafts.submit_draft("ventas", actor="ana@empresa.test")
    as_reviewer(review, monkeypatch, ["Sofibot.Revisor", "Tiendas"])
    page = review.get("/revision/ventas")
    response = review.post("/revision/ventas/publicar", data={"csrf": csrf(page)})
    assert "Another reviewer" in review.get(response.headers["location"]).text
    assert drafts.draft_status("ventas")["status"] == "submitted"


def test_writing_discards_the_preview(review, contract):
    drafts.build_preview("ventas", actor="pedro@eqz.test")
    assert drafts.preview_dir("ventas") is not None
    drafts.write_file("ventas", "generate.py", PREVIEW_CODE, actor="laura@eqz.test")
    assert drafts.preview_dir("ventas") is None and drafts.draft_status("ventas")["status"] == "draft"


def test_review_is_off_without_entra(api):
    assert api.get("/revision").status_code == 404


def test_failed_preview_is_shown_only_to_reviewers(review, monkeypatch):
    failing = PREVIEW_CODE + "raise ValueError('valor secreto 1234')\n"
    drafts.write_file("ventas", "generate.py", failing, actor="laura@eqz.test")
    drafts.submit_draft("ventas", actor="laura@eqz.test")
    as_reviewer(review, monkeypatch, ["Sofibot.Revisor", "Tiendas"])
    page = review.get("/revision/ventas")
    response = review.post("/revision/ventas/vista-previa", data={"csrf": csrf(page)})
    detail = review.get(response.headers["location"]).text
    assert "Error de la vista previa" in detail and "valor secreto 1234" in detail
    status = drafts.draft_status("ventas")          # what the author's AI can read
    assert "1234" not in json.dumps(status) and status["history"][-1]["operation"] == "vista previa fallida"
    drafts.write_file("ventas", "generate.py", PREVIEW_CODE, actor="laura@eqz.test")
    assert drafts.preview_error("ventas") is None   # a change discards the old error

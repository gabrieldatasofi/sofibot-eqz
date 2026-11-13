import json

import pytest

from sofibot_eqz import projects

WRITES_REPORT = """import argparse, pathlib
p = argparse.ArgumentParser(); p.add_argument('--output', type=pathlib.Path)
out = p.parse_args().output; out.mkdir(parents=True, exist_ok=True)
(out / 'index.html').write_text('{marker}')
"""


def make_project(root, slug, code, tables=("gold.month_store",)):
    project = root / "reports" / slug
    project.mkdir()
    manifest = {"slug": slug, "name": "Test"} | ({"tables": list(tables)} if tables is not None else {})
    (project / "report.json").write_text(json.dumps(manifest))
    (project / "generate.py").write_text(code)


def test_new_project_from_template(folders):
    project = projects.create("ventas-tiendas", 'Ventas "tiendas"', "gold.month_store")
    code = (project / "generate.py").read_text(encoding="utf-8")
    compile(code, "generate.py", "exec")
    assert "__" + "TABLE__" not in code and 'TABLE = "gold.month_store"' in code
    manifest = json.loads((project / "report.json").read_text(encoding="utf-8"))
    assert manifest["name"] == 'Ventas "tiendas"' and manifest["tables"] == ["gold.month_store"]
    assert list(projects.projects()) == ["ventas-tiendas"]


@pytest.mark.parametrize("slug, table", [("Ventas", "gold.t"), ("ok", "gold.t; DROP TABLE x")])
def test_new_project_validates_input(folders, slug, table):
    with pytest.raises(projects.ProjectError):
        projects.create(slug, "x", table)


def test_failed_build_keeps_the_previous_report(folders):
    make_project(folders, "demo", WRITES_REPORT.format(marker="v1"))
    target = projects.build("demo")
    assert (target / "index.html").read_text() == "v1"
    (folders / "reports" / "demo" / "generate.py").write_text("raise SystemExit(3)")
    with pytest.raises(projects.ProjectError, match="exit code 3"):
        projects.build("demo")
    assert (target / "index.html").read_text() == "v1"
    assert [report["slug"] for report in projects.built()] == ["demo"]


SEES_DECLARED_TABLES = """import argparse, os, pathlib
p = argparse.ArgumentParser(); p.add_argument('--output', type=pathlib.Path)
out = p.parse_args().output; out.mkdir(parents=True, exist_ok=True)
(out / 'index.html').write_text(os.environ['SOFIBOT_REPORT_TABLES'])
"""


def test_build_passes_the_declared_tables_and_keeps_them(folders):
    make_project(folders, "demo", SEES_DECLARED_TABLES, tables=["gold.Month_Store", "gold.month_product"])
    target = projects.build("demo")
    assert (target / "index.html").read_text() == "gold.month_product,gold.month_store"
    assert projects.built()[0]["tables"] == ["gold.month_product", "gold.month_store"]
    assert projects.built_tables("demo") == ["gold.month_product", "gold.month_store"]


@pytest.mark.parametrize("tables", [None, [], ["month_store"], ["dbo.month_store"], "gold.month_store"])
def test_build_requires_valid_gold_tables(folders, tables):
    make_project(folders, "demo", WRITES_REPORT.format(marker="v1"), tables=tables)
    with pytest.raises(projects.ProjectError, match="tables"):
        projects.build("demo")

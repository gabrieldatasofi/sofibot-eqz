import json

import pytest

from sofibot_eqz import projects

WRITES_REPORT = """import argparse, pathlib
p = argparse.ArgumentParser(); p.add_argument('--output', type=pathlib.Path)
out = p.parse_args().output; out.mkdir(parents=True, exist_ok=True)
(out / 'index.html').write_text('{marker}')
"""


def make_project(root, slug, code):
    project = root / "reports" / slug
    project.mkdir()
    (project / "report.json").write_text(json.dumps({"slug": slug, "name": "Test"}))
    (project / "generate.py").write_text(code)


def test_new_project_from_template(folders):
    project = projects.create("ventas-tiendas", 'Ventas "tiendas"', "gold.month_store")
    code = (project / "generate.py").read_text(encoding="utf-8")
    compile(code, "generate.py", "exec")
    assert "__" + "TABLE__" not in code and 'TABLE = "gold.month_store"' in code
    assert json.loads((project / "report.json").read_text(encoding="utf-8"))["name"] == 'Ventas "tiendas"'
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

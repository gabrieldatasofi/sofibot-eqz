"""Report projects: one folder per report in reports/, with report.json and generate.py.

report.json lists the Gold tables the report reads ("tables"): the portal shows the report
only to users whose roles cover all of them (access.py), and during the build every query is
checked against that list (db.Gold.check_declared).

A build runs generate.py in its own process with `--output <temporary folder>` and, if it
succeeds, swaps the folder into output/<slug>. A failed build never replaces a good report.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

from . import config
from .db import DECLARED_TABLES_VARIABLE

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
BUILD_LOCK = threading.Lock()  # one build at a time in the portal: scheduled, API or a reviewer's preview
TABLE = re.compile(r"\w+\.\w+")
TEMPLATE_DIR = Path(__file__).resolve().parent / "template"


class ProjectError(Exception):
    """output: the end of generate.py's output when it was captured (run(..., capture=True))."""

    def __init__(self, message: str, output: str = ""):
        super().__init__(message)
        self.output = output


def manifest(project: Path) -> dict:
    path = project / "report.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectError(f"{path}: {exc}") from exc
    for key in ("slug", "name"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ProjectError(f"{path}: missing '{key}'")
    if not SLUG.fullmatch(data["slug"]) or data["slug"] != project.name:
        raise ProjectError(f"{path}: slug must be lowercase-with-hyphens and equal to the folder name")
    tables = data.get("tables")
    if tables is not None:
        schema = os.environ.get("SQLSERVER_GOLD_SCHEMA", "gold").casefold()
        if (not isinstance(tables, list) or not tables
                or not all(isinstance(t, str) and TABLE.fullmatch(t) and t.split(".")[0].casefold() == schema for t in tables)):
            raise ProjectError(f'{path}: "tables" must list the Gold tables the report reads, e.g. ["{schema}.ventas_mes_tienda"]')
        data["tables"] = sorted({table.casefold() for table in tables})
    return data


def projects() -> dict[str, Path]:
    if not config.REPORTS_DIR.is_dir():
        return {}
    return {directory.name: directory for directory in sorted(config.REPORTS_DIR.iterdir())
            if (directory / "report.json").is_file() and (directory / "generate.py").is_file()}


def create(slug: str, name: str, table: str, description: str = "", root: Path | None = None) -> Path:
    """New project from the template in root (reports/ by default; drafts.py passes its own folder)."""
    if not SLUG.fullmatch(slug):
        raise ProjectError("The slug must be lowercase letters, digits and hyphens, e.g. ventas-tiendas")
    if not re.fullmatch(r"\w+\.\w+", table):
        raise ProjectError("The table must be schema.table, e.g. gold.ventas_mes_tienda")
    project = (root or config.REPORTS_DIR) / slug
    if project.exists():
        raise ProjectError(f"Already exists: {project}")
    shutil.copytree(TEMPLATE_DIR, project, ignore=shutil.ignore_patterns("__pycache__"))
    values = {"__SLUG__": slug, "__NAME__": name, "__DESCRIPTION__": description or name, "__TABLE__": table}
    for path in project.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for key, value in values.items():
                text = text.replace(key, json.dumps(value, ensure_ascii=False)[1:-1])
            path.write_text(text, encoding="utf-8")
    return project


def build(slug: str) -> Path:
    project = projects().get(slug)
    if project is None:
        raise ProjectError(f"Report project not found: {slug} (in {config.REPORTS_DIR})")
    return run(project, config.OUTPUT_DIR / slug)


def run(project: Path, target: Path, capture: bool = False) -> Path:
    """Run a project's generate.py into target, replacing it only if the run succeeds.

    build() writes into output/<slug>; drafts.py uses it for previews outside the portal, with
    capture=True so that a failure carries the end of the output (it may contain real values:
    only for people with access to the data, never for an AI assistant).
    """
    slug = project.name
    data = manifest(project)
    if "tables" not in data:
        raise ProjectError(f'{slug}: report.json must list the Gold tables the report reads, e.g. "tables": ["gold.ventas_mes_tienda"]')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{slug}-", dir=target.parent))
    try:
        result = subprocess.run([sys.executable, str(project / "generate.py"), "--output", str(staging)],
                                cwd=project, env={**os.environ, DECLARED_TABLES_VARIABLE: ",".join(data["tables"])},
                                timeout=config.BUILD_TIMEOUT, capture_output=capture,
                                text=capture, errors="replace" if capture else None)
        if result.returncode:
            output = ((result.stdout or "") + (result.stderr or ""))[-4000:] if capture else ""
            if output:
                sys.stderr.write(output)  # still in the server log, as without capture
            raise ProjectError(f"{slug}: generate.py failed with exit code {result.returncode}", output)
        if not (staging / "index.html").is_file() and not any(staging.glob("*.xlsx")):
            raise ProjectError(f"{slug}: generate.py produced neither index.html nor an .xlsx file")
        (staging / "report.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        replace(staging, target)
    except subprocess.TimeoutExpired as exc:
        raise ProjectError(f"{slug}: generate.py exceeded {config.BUILD_TIMEOUT} s") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target


def replace(source: Path, target: Path) -> None:
    """Swap a finished build into target; the old one is removed only after the swap."""
    previous = target.parent / f".{target.name}-previous"
    shutil.rmtree(previous, ignore_errors=True)
    if target.exists():
        target.rename(previous)
    source.rename(target)
    shutil.rmtree(previous, ignore_errors=True)


def built_tables(slug: str) -> list[str]:
    """Gold tables a built report was made from (empty if unknown: only "*" roles see it)."""
    try:
        tables = json.loads((config.OUTPUT_DIR / slug / "report.json").read_text(encoding="utf-8")).get("tables")
    except (OSError, ValueError, AttributeError):
        return []
    return [table for table in tables if isinstance(table, str)] if isinstance(tables, list) else []


def built() -> list[dict]:
    """Reports in output/, newest first, with links to their HTML page and Excel files."""
    reports = []
    if not config.OUTPUT_DIR.is_dir():
        return reports
    for directory in config.OUTPUT_DIR.iterdir():
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        try:
            data = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        reports.append({
            "slug": directory.name, "name": data.get("name", directory.name),
            "description": data.get("description", ""), "built_at": directory.stat().st_mtime,
            "tables": built_tables(directory.name),
            "html": f"/output/{directory.name}/" if (directory / "index.html").is_file() else None,
            "excel": [f"/output/{directory.name}/{path.name}" for path in sorted(directory.glob("*.xlsx"))],
        })
    return sorted(reports, key=lambda report: report["built_at"], reverse=True)

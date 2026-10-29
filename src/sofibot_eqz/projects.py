"""Report projects: one folder per report in reports/, with report.json and generate.py.

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

from . import config

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
TEMPLATE_DIR = Path(__file__).resolve().parent / "template"


class ProjectError(Exception):
    pass


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
    return data


def projects() -> dict[str, Path]:
    if not config.REPORTS_DIR.is_dir():
        return {}
    return {directory.name: directory for directory in sorted(config.REPORTS_DIR.iterdir())
            if (directory / "report.json").is_file() and (directory / "generate.py").is_file()}


def create(slug: str, name: str, table: str, description: str = "") -> Path:
    if not SLUG.fullmatch(slug):
        raise ProjectError("The slug must be lowercase letters, digits and hyphens, e.g. ventas-tiendas")
    if not re.fullmatch(r"\w+\.\w+", table):
        raise ProjectError("The table must be schema.table, e.g. gold.ventas_mes_tienda")
    project = config.REPORTS_DIR / slug
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
    data = manifest(project)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = config.OUTPUT_DIR / slug
    staging = Path(tempfile.mkdtemp(prefix=f".{slug}-", dir=config.OUTPUT_DIR))
    try:
        result = subprocess.run([sys.executable, str(project / "generate.py"), "--output", str(staging)],
                                cwd=project, env=dict(os.environ), timeout=config.BUILD_TIMEOUT)
        if result.returncode:
            raise ProjectError(f"{slug}: generate.py failed with exit code {result.returncode}")
        if not (staging / "index.html").is_file() and not any(staging.glob("*.xlsx")):
            raise ProjectError(f"{slug}: generate.py produced neither index.html nor an .xlsx file")
        (staging / "report.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        previous = config.OUTPUT_DIR / f".{slug}-previous"
        shutil.rmtree(previous, ignore_errors=True)
        if target.exists():
            target.rename(previous)
        staging.rename(target)
        shutil.rmtree(previous, ignore_errors=True)
    except subprocess.TimeoutExpired as exc:
        raise ProjectError(f"{slug}: generate.py exceeded {config.BUILD_TIMEOUT} s") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target


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
            "html": f"/output/{directory.name}/" if (directory / "index.html").is_file() else None,
            "excel": [f"/output/{directory.name}/{path.name}" for path in sorted(directory.glob("*.xlsx"))],
        })
    return sorted(reports, key=lambda report: report["built_at"], reverse=True)

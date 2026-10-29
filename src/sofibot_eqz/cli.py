"""sofibot: command line of Sofibot for Equivalenza.

    sofibot check                       test the SQL Server connection (reads no rows)
    sofibot schema                      write reports/gold_schema.json (structure only)
    sofibot new SLUG --name N --table gold.T   create a report project from the template
    sofibot list                        list report projects and built reports
    sofibot build SLUG [SLUG ...]       build reports into output/ (or --all)
    sofibot serve                       start the web portal (http://localhost:8080)
"""
import argparse
import json
import sys


def check(_args) -> int:
    from .db import Gold, connection_hint

    try:
        info = Gold().server_info()
    except Exception as exc:  # pyodbc errors carry the driver's explanation (login, TLS, network)
        print(f"ERROR: could not connect: {exc}", file=sys.stderr)
        if hint := connection_hint(exc):
            print(f"\nQUÉ HACER: {hint}", file=sys.stderr)
        print("Más ayuda: docs/solucion-de-problemas.md", file=sys.stderr)
        return 1
    print(json.dumps(info, indent=2, ensure_ascii=False))
    problems = []
    if not info["schema_exists"]:
        problems.append(f"schema '{info['schema']}' does not exist or the login cannot see it")
    elif not info["tables"]:
        problems.append(f"the login sees no tables or views in schema '{info['schema']}'")
    if not info["read_only_login"]:
        problems.append("the login can write or owns the database: use a SELECT-only login")
    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)
    print("Connection OK" if not problems else "Connection OK, with warnings")
    return 0


def schema(args) -> int:
    from . import config
    from .schema import describe

    contract = json.dumps(describe(), indent=2, ensure_ascii=False) + "\n"
    if args.stdout:
        print(contract, end="")
        return 0
    config.SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SCHEMA_FILE.write_text(contract, encoding="utf-8")
    print(f"Wrote {config.SCHEMA_FILE}")
    return 0


def new(args) -> int:
    from .projects import create

    project = create(args.slug, args.name, args.table, args.description)
    print(f"Created {project}\nEdit {project / 'generate.py'} and run: sofibot build {args.slug}")
    return 0


def list_projects(_args) -> int:
    from .projects import built, manifest, projects

    found = projects()
    outputs = {report["slug"] for report in built()}
    if not found:
        print("No report projects yet. Create one with: sofibot new <slug> --name ... --table gold.<table>")
    for slug, project in found.items():
        print(f"{slug:32} {'built ' if slug in outputs else 'not built'}  {manifest(project)['name']}")
    return 0


def build(args) -> int:
    from .projects import ProjectError, build as build_one, projects

    slugs = list(projects()) if args.all else args.slugs
    if not slugs:
        print("Name the reports to build, or use --all", file=sys.stderr)
        return 2
    failed = 0
    for slug in slugs:
        try:
            print(f"Built {build_one(slug)}")
        except ProjectError as exc:
            failed += 1
            print(f"ERROR: {exc}", file=sys.stderr)
    return 1 if failed else 0


def serve(args) -> int:
    import uvicorn

    uvicorn.run("sofibot_eqz.server:app", host=args.host, port=args.port, access_log=False)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sofibot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    commands.add_parser("check", help="test the SQL Server connection").set_defaults(run=check)
    command = commands.add_parser("schema", help="write the Gold schema contract")
    command.add_argument("--stdout", action="store_true", help="print it instead of writing reports/gold_schema.json")
    command.set_defaults(run=schema)
    command = commands.add_parser("new", help="create a report project")
    command.add_argument("slug", help="folder name: lowercase words joined by '-', e.g. ventas-tiendas")
    command.add_argument("--name", required=True, help="title shown in the portal")
    command.add_argument("--table", required=True, help="main Gold table, e.g. gold.ventas_mes_tienda")
    command.add_argument("--description", default="")
    command.set_defaults(run=new)
    commands.add_parser("list", help="list report projects").set_defaults(run=list_projects)
    command = commands.add_parser("build", help="build reports into output/")
    command.add_argument("slugs", nargs="*")
    command.add_argument("--all", action="store_true", help="build every project in reports/")
    command.set_defaults(run=build)
    command = commands.add_parser("serve", help="start the web portal")
    command.add_argument("--host", default="127.0.0.1")
    command.add_argument("--port", type=int, default=8080)
    command.set_defaults(run=serve)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except Exception as exc:  # configuration and project errors: one clear line, no traceback
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

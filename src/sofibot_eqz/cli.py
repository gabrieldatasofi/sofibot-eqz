"""sofibot: command line of Sofibot for Equivalenza.

    sofibot config [--consultas]        which settings are filled in or missing (never their values)
    sofibot check                       test the SQL Server connection (reads no rows)
    sofibot schema                      write reports/gold_schema.json (structure only)
    sofibot new SLUG --name N --table gold.T   create a report project from the template
    sofibot list                        list report projects and built reports
    sofibot build SLUG [SLUG ...]       build reports into output/ (or --all)
    sofibot permissions                 check reports/permisos.json (who sees which report)
    sofibot drafts                      list report drafts written through the API
    sofibot publish SLUG                copy a reviewed draft into reports/ (then build it)
    sofibot reject SLUG --comment C     send a draft back with a comment
    sofibot serve                       start the web portal (http://localhost:8080)

  Functionality 2, data queries (docs/11-consultas.md):
    sofibot catalog                     check reports/catalogo.json against the schema contract
    sofibot serve-consultas             start the query service (its own container)
    sofibot consultas-registro TABLE --out FILE.csv   export the query record (no values)
"""
import argparse
import json
import sys


def show_config(args) -> int:
    from .settings_check import review

    lines, problems = review(service="consultas" if args.consultas else "portal")
    print("\n".join(lines))
    print()
    for problem in problems:
        print(f"FALTA: {problem}")
    target = ".env.consultas" if args.consultas else ".env"
    print("Configuración completa" if not problems else f"Hay {len(problems)} cosas por corregir en {target}")
    return 0 if not problems else 1


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


def permissions(_args) -> int:
    """Check reports/permisos.json against the report projects and the Gold schema contract.

    Prints role names, table names and report names only: no data.
    """
    from . import config
    from .access import ALL, PermissionsError, covers, permissions_file, read
    from .projects import ProjectError, manifest, projects

    try:
        roles = read()
    except PermissionsError as exc:
        print(f"ERROR: {exc}\nFormat: docs/09-inicio-sesion-entra.md", file=sys.stderr)
        return 1
    problems, reports = [], {}
    for slug, project in projects().items():
        try:
            reports[slug] = set(manifest(project).get("tables") or [])
        except ProjectError as exc:
            problems.append(str(exc))
            continue
        if not reports[slug]:
            problems.append(f"'{slug}' does not list its Gold tables in report.json: only roles with \"*\" will see it")
    print(f"{permissions_file()}:")
    for role, tables in sorted(roles.items()):
        seen = [slug for slug, report_tables in reports.items() if covers(tables, report_tables)]
        print(f"  {role}\n    tables:  {'all' if ALL in tables else ', '.join(sorted(tables)) or '(none)'}"
              f"\n    reports: {', '.join(seen) or '(none)'}")
    schema_file = config.REPORTS_DIR / config.SCHEMA_FILE.name
    try:
        contract = json.loads(schema_file.read_text(encoding="utf-8"))
        known = {name.casefold() for name in contract["tables"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        known = None
    if known:
        problems += [f"role '{role}' lists '{table}', which is not in {schema_file.name}"
                     for role, tables in sorted(roles.items()) for table in sorted(tables) if table != ALL and table not in known]
    # A report needs all its tables in one role or across several: warn when nobody could have them all.
    everything = set().union(*roles.values()) if roles else set()
    problems += [f"no role can see '{slug}': its tables {', '.join(sorted(t for t in tables if t not in everything))} are in no role"
                 for slug, tables in reports.items() if tables and not covers(everything, tables)]
    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)
    return 0


CLI_ACTOR = "línea de comandos del servidor"


def list_drafts(_args) -> int:
    from . import config
    from .drafts import list_drafts as found

    drafts = found()
    if not drafts:
        print(f"No drafts in {config.DRAFTS_DIR}")
    for draft in drafts:
        print(f"{draft['slug']:32} {draft['status']:10} {draft.get('updated_at', '')[:16]:16}  {draft['name']}")
        if draft.get("comment"):
            print(f"{'':32} comment: {draft['comment']}")
    if drafts:
        print(f"\nReview the code in {config.DRAFTS_DIR}/<slug>/ before publishing.")
    return 0


def publish(args) -> int:
    from .drafts import DraftError, publish as publish_draft

    try:
        result = publish_draft(args.slug, force=args.force, actor=CLI_ACTOR)
    except DraftError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Published {args.slug} into reports/{args.slug}")
    if result["previous_code"]:
        print(f"Previous code kept in {result['previous_code']}")
    print(f"Build it now with: sofibot build {args.slug} (or wait for the scheduled build)")
    return 0


def reject(args) -> int:
    from .drafts import DraftError, reject as reject_draft

    try:
        reject_draft(args.slug, args.comment, actor=CLI_ACTOR)
    except DraftError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Rejected {args.slug}")
    return 0


def serve(args) -> int:
    import uvicorn

    uvicorn.run("sofibot_eqz.server:app", host=args.host, port=args.port, access_log=False)
    return 0


def catalog(_args) -> int:
    """Check reports/catalogo.json: structure, and tables and columns against gold_schema.json."""
    from . import config
    from .consultas.catalog import CatalogError, catalog_file, load, problems_against

    try:
        entries = load()
    except CatalogError as exc:
        print(f"ERROR: {exc}\nFormat: docs/11-consultas.md", file=sys.stderr)
        return 1
    print(f"{catalog_file()}:")
    for table, spec in entries.items():
        print(f"  {table}\n    measures:   {', '.join(spec['measures'])}\n"
              f"    dimensions: {', '.join(spec['dimensions']) or '(none)'}\n    period:     {spec['period'] or '(none)'}")
    try:
        contract = json.loads((config.REPORTS_DIR / config.SCHEMA_FILE.name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("WARNING: reports/gold_schema.json is missing: tables and columns were not checked", file=sys.stderr)
        return 0
    problems = problems_against(entries, contract)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    return 1 if problems else 0


def serve_consultas(args) -> int:
    import uvicorn

    uvicorn.run("sofibot_eqz.consultas.server:app", host=args.host, port=args.port, access_log=False)
    return 0


def query_record(args) -> int:
    from pathlib import Path

    from .consultas.audit import export

    count = export(args.table, Path(args.out))
    print(f"Wrote {count} rows of {args.table} to {args.out}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sofibot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    command = commands.add_parser("config", help="which settings are filled in or missing (never their values)")
    command.add_argument("--consultas", action="store_true", help="check the query service settings (.env.consultas)")
    command.set_defaults(run=show_config)
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
    commands.add_parser("permissions", help="check reports/permisos.json (Entra ID sign-in)").set_defaults(run=permissions)
    commands.add_parser("drafts", help="list report drafts written through the API").set_defaults(run=list_drafts)
    command = commands.add_parser("publish", help="copy a reviewed draft into reports/")
    command.add_argument("slug")
    command.add_argument("--force", action="store_true", help="publish even if the draft was not submitted")
    command.set_defaults(run=publish)
    command = commands.add_parser("reject", help="send a draft back with a comment")
    command.add_argument("slug")
    command.add_argument("--comment", default="", help="what to change; shown to whoever wrote the draft")
    command.set_defaults(run=reject)
    command = commands.add_parser("serve", help="start the web portal")
    command.add_argument("--host", default="127.0.0.1")
    command.add_argument("--port", type=int, default=8080)
    command.set_defaults(run=serve)
    commands.add_parser("catalog", help="check the query catalog (reports/catalogo.json)").set_defaults(run=catalog)
    command = commands.add_parser("serve-consultas", help="start the query service")
    command.add_argument("--host", default="127.0.0.1")
    command.add_argument("--port", type=int, default=8080)
    command.set_defaults(run=serve_consultas)
    command = commands.add_parser("consultas-registro", help="export the query record to CSV (no values)")
    command.add_argument("table", choices=["consultas", "preguntas"])
    command.add_argument("--out", required=True, help="CSV file to write")
    command.set_defaults(run=query_record)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except Exception as exc:  # configuration and project errors: one clear line, no traceback
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

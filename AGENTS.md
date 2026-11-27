# Security policy (read first)

AI assistants never see the client's data by any means: no rows, totals, counts, date
ranges, query results, built reports, Excel files or build logs computed from real data.
Work only from the schema contract `reports/gold_schema.json` and write code; a person
reviews it, builds it against the real data and checks the result.

When a rule blocks an action, stop, say which rule blocks it (docs/06-seguridad.md) and
propose the safe alternative (a person running the step, or the Contoso example
database). Do not look for workarounds.

- Never read `.env`, `output/`, `*.xlsx`, `*.csv` or any built report.
- Never run `sofibot build`, `sofibot check`, `generate.py`, `sqlcmd` or ad-hoc SQL
  against a client database. Never ask for or use client credentials.
- Never run `sofibot local-account` (it shows or asks for passwords and TOTP secrets: a
  person runs it), never read `acceso/cuentas-locales.json` or `acceso/cuentas-totp.json`,
  and never ask for or use a local account's password, TOTP code or personal token.
- The only exception is the public Contoso example on a Datasofi development machine,
  through its own environment: `docker compose -f examples/contoso/compose.yaml ...`, whose
  configuration (`examples/contoso/.env`, never read either) only ever points at the
  Contoso database. Never run these commands with the project's `compose.yaml` or `.env`.
  Even with Contoso, report only whether a build passed and its structure, not values, and
  never read `examples/contoso/output/`.

# The product's query agent is not an exception for you

Sofibot may include a query feature where an LLM answers end users with Gold data, within
each user's permissions. That is product behaviour, approved by the client (which model
and provider receive the data) and documented in docs/06-seguridad.md. It is not an
exception to the policy above: while designing, building, testing or debugging that
feature, you still never see the client's data. Use the Contoso example or synthetic
data, never the client's database, the query API, its MCP server or its audit table.

# Writing a report

Use the `nuevo-informe` skill (.claude/skills/nuevo-informe/SKILL.md). In short:

- A report is `reports/<slug>/report.json` + `generate.py`. Create it with
  `sofibot new <slug> --name "..." --table gold.<table>` and edit the template.
- `report.json` "tables" lists every Gold table `generate.py` reads: the build fails on any
  other, and portal permissions (`acceso/permisos.json`) are granted per table.
- Read only Gold tables listed in `reports/gold_schema.json`, through
  `sofibot_eqz.Gold`: one connection per report, `?` parameters for every variable value.
- HTML page with `Report` (lang `es`), Excel with `Workbook`. Give `Workbook` real
  numbers, dates and Decimals, not formatted strings.
- Ratios come from totals (total margin / total sales), never averages of row ratios.
  Whole calendar months. NULL sums mean no data, not zero. Never add totals from two
  Gold tables that describe the same facts. Respect the column descriptions.
- `generate.py` never prints data values.

# Code in this repository

- `src/sofibot_eqz/`: package (db, schema, html, excel, projects, cli, server; pages: ui,
  pages, review, admin). Architecture: docs/12-arquitectura.md.
  Two separate functionalities share only `identity.py` (Entra ID tokens, function roles)
  and `access.py` (roles per user and tables per role, in `acceso/`; Entra only signs in;
  local accounts with Sofibot's own tokens, docs/09):
  - functionality 1, writing reports: `drafts.py`, `review.py`, `report_guide.md` (keep it in
    sync with docs/04 and the skill), `/api/code`, `mcp-server/sofibot_informes_mcp.py`; docs/10;
  - functionality 2, data queries: `consultas/` (its own app, container and settings),
    `mcp-server/sofibot_consultas_mcp.py`; the portal's /consultas page only forwards the
    user's own token to it; docs/11.
  Never add a data path from one to the other.
- `instalacion/`: AI-assistant rules shipped at the root of the install package (`AGENTS.md`,
  `CLAUDE.md`, `.claude/settings.json`); keep them in sync with docs/00-instalacion-con-ia.md
  (shipped as `INSTALAR-CON-IA.md`) and `publicar-imagen.ps1`.
- Docs for the client in `docs/` (Spanish). Keep them in sync with behaviour changes.
- Tests: `pytest` (no database needed).
- Datasofi visual style: blue #2C3968, orange #D16B1B, cyan #279CDB, teal #5DAEAB, Roboto.

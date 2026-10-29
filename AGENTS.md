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
- The only exception is the public Contoso example (examples/contoso) on a Datasofi
  development machine whose `.env` points at the Contoso database; even there, report
  only whether a build passed and its structure, not values.

# Writing a report

Use the `nuevo-informe` skill (.claude/skills/nuevo-informe/SKILL.md). In short:

- A report is `reports/<slug>/report.json` + `generate.py`. Create it with
  `sofibot new <slug> --name "..." --table gold.<table>` and edit the template.
- Read only Gold tables listed in `reports/gold_schema.json`, through
  `sofibot_eqz.Gold`: one connection per report, `?` parameters for every variable value.
- HTML page with `Report` (lang `es`), Excel with `Workbook`. Give `Workbook` real
  numbers, dates and Decimals, not formatted strings.
- Ratios come from totals (total margin / total sales), never averages of row ratios.
  Whole calendar months. NULL sums mean no data, not zero. Never add totals from two
  Gold tables that describe the same facts. Respect the column descriptions.
- `generate.py` never prints data values.

# Code in this repository

- `src/sofibot_eqz/`: package (db, schema, html, excel, projects, cli, server).
- Docs for the client in `docs/` (Spanish). Keep them in sync with behaviour changes.
- Tests: `pytest` (no database needed).
- Datasofi visual style: blue #2C3968, orange #D16B1B, cyan #279CDB, teal #5DAEAB, Roboto.

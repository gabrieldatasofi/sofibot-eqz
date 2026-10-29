---
name: nuevo-informe
description: Create a new Sofibot report (HTML page and/or Excel file) over the Gold tables in SQL Server, from the schema contract only. Use when the user asks to create, build or design a new report, informe, dashboard or Excel export.
---

# New Sofibot report from the schema only

You never see the client's data. You read the schema contract, write the report code, and
a person builds it against the database. Follow these steps in order and do not explore
the rest of the repository.

Security: this flow implements docs/06-seguridad.md and AGENTS.md. If a step is blocked by
a policy or permission rule, stop, say which rule blocks it and propose the safe
alternative; never work around it.

## 1. Read the schema contract

Read `reports/gold_schema.json`: tables, columns, types and descriptions, no data. If it
does not exist, ask the user to run `docker compose run --rm sofibot sofibot schema` and
wait. Respect what the descriptions say about grain, currency, taxes, NULL and columns
that cannot be summed.

## 2. Agree on the report

Unless the request already says it, ask one question:

> **¿Quieres un informe rápido (formato estándar, sin más preguntas) o uno más completo
> (te hago 2 o 3 preguntas)?** ¿Y lo quieres como página web, como Excel o ambos?

Quick report defaults:

| Decision | Default |
|---|---|
| Output | HTML page + Excel |
| Period | Last 12 whole months up to the latest month in the table (`SELECT MAX(<month column>)`) |
| KPIs | The main amounts summed over the period, plus margin % if cost or margin exists |
| Charts | Monthly trend (`width='full'`, `views` per metric) + top 10 by the main dimension |
| Table | Ranking by the main dimension with `filters=[...]` on text columns |
| Excel | One sheet per table in the page plus a monthly detail sheet |

For a complete report, ask only what is missing: the question it answers, period and
comparison, breakdown (dimension), audience (management or analysts), output (page, Excel).
If the request needs something the schema does not have, say so and propose the closest
report the schema supports.

## 3. Create the project

```bash
sofibot new <slug> --name "<Título>" --table gold.<main table> --description "<one sentence>"
```

`<slug>`: lowercase words joined by `-`. If `sofibot` is not installed locally, ask the
user to run it through Docker (`docker compose run --rm sofibot sofibot new ...`) or create
the two files by copying `src/sofibot_eqz/template/` by hand.

## 4. Write `reports/<slug>/generate.py`

Edit the template and use `examples/contoso/reports/contoso-ventas-tiendas/generate.py`
as the model for a complete report. Rules:

- `gold = Gold()`, `with gold.connect() as con:` and every query with
  `gold.query(sql, [params], connection=con)`. `?` parameters for every value; table and
  column names only from the schema contract.
- Whole months: `WHERE <month> BETWEEN ? AND ?`. Disclose the period in the subtitle or a note.
- Ratios from totals; never average row ratios; never add totals from different Gold
  tables; NULL means no data ("Sin datos").
- Page: `Report.from_manifest(PROJECT, subtitle=..., kpi_columns=..., lang="es")`, KPIs,
  `Chart(..., views=...)` for switchable metrics, tables with `filters=[...]` and
  `source=TableSource(TABLE, "gold", [grain columns])`, `add_link("Descargar Excel", "<file>.xlsx")`.
  Spanish labels, Datasofi colours (BLUE, ORANGE, CYAN, TEAL).
- Excel: `Workbook.from_manifest(PROJECT, subtitle=...)`, `add_sheet`/`add_query` with real
  values and `formats` (`eur`, `usd`, `percent`, `integer`, `month`...), a note with definitions.
- The final `print` only names the report.

Check that the file compiles: `python -m py_compile reports/<slug>/generate.py`.

## 5. Hand over

Summarise in 3 to 5 lines what the report shows, which Gold tables and columns it reads,
and the outputs (page, Excel sheets). Then tell the user to build and review it:

```bash
docker compose run --rm sofibot sofibot build <slug>
```

Do not run the build yourself against a client database. If it fails, ask the user for
the error message **without data values** (the Python traceback and the SQL Server error
number are enough) and fix the code.

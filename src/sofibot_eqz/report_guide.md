# Writing a Sofibot report through the report-code API

You never see the client's data. You act for the signed-in author: you read the schema of
the Gold tables their roles allow, write the report code in a draft, and a reviewer (a
person) previews it against the database and publishes it. Never try to read data by any
other means, and never print data values from `generate.py`.

Keep this guide in sync with docs/04-crear-informes.md and the `nuevo-informe` skill.

## Steps

1. **Schema**: `describe_schema` (this document comes with it). Use only the tables and
   columns it lists, and respect what the descriptions say about grain, currency, taxes,
   NULL and columns that cannot be summed. If the request needs something the schema does
   not have, say so and propose the closest report it supports.
2. **Agree on the report.** Unless the request already says it, ask once: quick report
   (standard format) or complete (2 or 3 questions), and page, Excel or both.
   Quick defaults: page + Excel; last 12 whole months up to the latest month in the table
   (`SELECT MAX(<month column>)`); KPIs for the main amounts plus margin % if cost or margin
   exists; monthly trend chart (`width="full"`) + top 10 by the main dimension; ranking table
   with `filters=[...]`; Excel with one sheet per page table plus a monthly detail sheet.
3. **Draft**: `list_reports` shows the published reports. Create a draft with
   `create_draft(slug, name, table, description)` (slug: lowercase words joined by `-`;
   table: the main Gold table) or, to change a published report,
   `create_draft(slug, from_report=true)`. Then `read_file` and `write_file` its
   `generate.py` and `report.json`.
4. **`report.json` "tables"** must list every Gold table the report reads, and no other:
   the build fails on any other table, and the portal shows the report only to users whose
   roles cover all of them.
5. **Check**: `check_draft` until it passes. It is static (syntax, report.json, tables
   against the contract and the author's tables): it runs no code, so write the queries
   carefully.
6. **Submit** with `submit_draft` only when the user asks. A reviewer reads the code,
   builds a preview and publishes it, or rejects it with a comment. `draft_status` shows
   the status, who did what and, if rejected, the comment. If the preview fails, ask for
   the error **without data values** (Python traceback, SQL Server error number) and fix
   the draft; any change sends it back to "draft", to submit again.

## Rules for `generate.py`

- Never write into the code values, names or figures you saw anywhere (a query, a previous
  answer, the user's message): filters, rankings and lists are computed by the report's SQL
  from the data at build time. The report must stay right when the data changes.

- `gold = Gold()`, `with gold.connect() as con:`, and every query with
  `gold.query(sql, [params], connection=con)`: one connection per report, `?` parameters
  for every variable value, table and column names only from the schema contract.
- Whole calendar months: `WHERE <month> BETWEEN ? AND ?`; state the period in the subtitle
  or a note.
- Ratios from totals (total margin / total sales), never averages of row ratios. Never add
  totals from two Gold tables that describe the same facts. NULL sums mean no data
  ("Sin datos"), not zero.
- Give tables and Excel sheets real numbers, dates and Decimals, never formatted strings.
- Spanish labels (`lang="es"`), Datasofi colours `BLUE`, `ORANGE`, `CYAN`, `TEAL`.
- Keep the template's `if __name__ == "__main__":` block. The final `print` only names
  the report.

## Skeleton

```python
import argparse
from datetime import date
from pathlib import Path

from sofibot_eqz import Chart, Gold, Report, TableSource, Workbook

PROJECT = Path(__file__).resolve().parent
TABLE = "gold.ventas_mes_tienda"


def generate(output: Path) -> None:
    gold = Gold()
    with gold.connect() as con:
        last = gold.query(f"SELECT MAX(mes) FROM {TABLE}", connection=con)[1][0][0]
        first = date(last.year - 1, last.month, 1)          # 12 whole months ending at `last`
        columns, rows = gold.query(
            f"SELECT tienda AS Tienda, SUM(ventas_eur) AS Ventas, SUM(margen_eur) AS Margen FROM {TABLE} "
            "WHERE mes > ? AND mes <= ? GROUP BY tienda ORDER BY Ventas DESC", [first, last], connection=con)

    report = Report.from_manifest(PROJECT, subtitle=f"{first:%m/%Y} – {last:%m/%Y}", lang="es")
    report.add_chart(Chart.bar("Ventas por tienda", [r[0] for r in rows[:10]], [float(r[1] or 0) for r in rows[:10]]))
    report.add_table("Tiendas", columns, rows, formats={"Ventas": "eur", "Margen": "eur"},
                     filters=["Tienda"], source=TableSource(TABLE, "gold"))
    report.add_link("Descargar Excel", "ventas.xlsx")
    report.write(output)

    workbook = Workbook.from_manifest(PROJECT, subtitle=f"{first:%m/%Y} – {last:%m/%Y}")
    workbook.add_sheet("Tiendas", columns, rows, formats={"Ventas": "eur", "Margen": "eur"}, source=TABLE)
    workbook.write(output / "ventas.xlsx")
    print("Generated ventas")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    generate(parser.parse_args().output)
```

## API reference

Reading: `gold.query(sql, params, connection=con)` returns `(column names, rows as tuples)`;
`gold.dataframe(...)` returns a pandas DataFrame. Types: `date`/`datetime`, `Decimal`, `int`,
`str`, `None` for NULL.

Page, `Report.from_manifest(PROJECT, subtitle="", kpi_columns=4, lang="es")`:

| Method | Adds |
|---|---|
| `add_kpi(label, value, detail="", format=None)` | KPI card. `format`: `integer`, `number`, `percent` (0.25 → 25 %), `currency` (USD); for euros pass text such as `f"{v:,.0f} €"` |
| `add_chart(Chart.bar/line/pie(title, labels, values))` | Chart; `Chart.bar(..., orientation="h")` for horizontal bars; `width="half"` or `"full"` |
| `add_chart(Chart(title, traces, views={"Ventas": t1, "Margen": t2}))` | Free Plotly chart with view buttons |
| `add_table(title, columns, rows, formats={...}, filters=[...], source=TableSource(TABLE, "gold"))` | Table; with `filters` it gets search, column drop-downs and sorting |
| `add_link(text, href)` / `add_note(text)` | Link under the title / note at the end |

Interactive reports (filter bar, recomputed in the browser): one aggregated
`add_dataset(name, columns, rows, formats=...)` (e.g. month × store, limited period, tens
of thousands of rows at most), `add_filter(label, column, kind="select"|"range", default=..., compare=False)`,
then `add_dynamic_kpi(label, dataset, measure, format=...)`,
`add_dynamic_chart(title, dataset, x, [(name, measure)], kind="line"|"bar"|"hbar", order="x"|"desc", top=n, width="half"|"full")`
(`order="x"` keeps the x axis order, `order="desc"` sorts by the **first** series: put the
series to rank by first; no other values are accepted; `x` may be
`{"Mes": "Mes", "Año": "Año"}` for granularity buttons) and
`add_dynamic_table(title, dataset, columns, [(name, measure, format)])`. Measures:
`Sum(col)`, `Ratio(numerator, denominator)`, `Distinct(col)`, plus `.vs_previous()` and
`.previous()` with a `compare=True` filter. Dynamic KPI formats: `currency`, `eur`, `usd`,
`integer`, `number`, `percent`, `change`, `pp`.

Excel, `Workbook.from_manifest(PROJECT, subtitle="")`: `add_sheet(name, columns, rows, formats=..., source=TABLE)`,
`add_query(name, gold.query(...), source=TABLE)`, `add_dataframe(name, df)`, `add_note(text)`,
`write(output / "<file>.xlsx")`. Formats (page and Excel): `eur`/`currency`, `usd`,
`percent`, `integer`, `number`, `date`, `datetime`, `month`, `text`.

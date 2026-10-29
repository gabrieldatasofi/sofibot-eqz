"""__NAME__: informe sobre __TABLE__ (página HTML + Excel).

Creado con `sofibot new`. Funciona tal cual: exporta la tabla completa. Cámbialo por las
consultas, KPIs y gráficos del informe (docs/04-crear-informes.md) y constrúyelo con
`sofibot build __SLUG__`.
"""
import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sofibot_eqz import Gold, Report, TableSource, Workbook

PROJECT = Path(__file__).resolve().parent
TABLE = "__TABLE__"
PREVIEW_ROWS = 1000  # filas en la página HTML; el Excel lleva todas


def cell(value) -> str:
    """Texto para la tabla HTML. El Excel recibe los valores originales."""
    if value is None:
        return ""
    if isinstance(value, (Decimal, float)):
        return f"{value:,.2f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def generate(output: Path) -> None:
    gold = Gold()
    with gold.connect() as con:
        # Una conexión por informe. Usa ? para cualquier valor variable: gold.query(sql, [valor], connection=con)
        columns, rows = gold.query(f"SELECT * FROM {TABLE}", connection=con)

    report = Report.from_manifest(PROJECT, lang="es")
    report.add_kpi("Filas", len(rows), format="integer", detail=TABLE)
    text_columns = [name for index, name in enumerate(columns) if rows and isinstance(rows[0][index], str)][:3]
    report.add_table(TABLE, columns, [[cell(value) for value in row] for row in rows[:PREVIEW_ROWS]],
                     source=TableSource(TABLE, TABLE.split(".")[0]), filters=text_columns)
    if len(rows) > PREVIEW_ROWS:
        report.add_note(f"La página muestra las primeras {PREVIEW_ROWS:,} filas; el Excel las incluye todas.")
    report.add_link("Descargar Excel", "__SLUG__.xlsx")
    report.write(output)

    workbook = Workbook.from_manifest(PROJECT)
    workbook.add_sheet("Datos", columns, rows, source=TABLE)
    workbook.write(output / "__SLUG__.xlsx")
    print("Generated __SLUG__")  # nunca imprimir valores de datos


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    generate(parser.parse_args().output)

"""Contoso · Ventas por tienda: informe completo (KPIs, gráficos, tabla interactiva) + Excel.


Lee gold.month_store (examples/contoso/01-crear-gold.sql). Construir con:
    sofibot build contoso-ventas-tiendas
"""
import argparse
from datetime import date
from pathlib import Path

from sofibot_eqz import Chart, Gold, Report, TableSource, Workbook

BLUE, ORANGE, CYAN, TEAL = "#2C3968", "#D16B1B", "#279CDB", "#5DAEAB"
PROJECT = Path(__file__).resolve().parent
TABLE = "gold.month_store"


def months_back(month: date, count: int) -> date:
    index = month.year * 12 + month.month - 1 - count
    return date(index // 12, index % 12 + 1, 1)


def generate(output: Path) -> None:
    gold = Gold()
    with gold.connect() as con:
        def query(sql, parameters=()):
            return gold.query(sql, parameters, connection=con)[1]

        latest = query(f"SELECT MAX(month) FROM {TABLE}")[0][0]
        if latest is None:
            raise ValueError(f"{TABLE} is empty")
        period = [months_back(latest, 11), latest]  # 12 meses completos hasta el último disponible
        monthly = query(f"SELECT month, SUM(sales_usd), SUM(gross_profit_usd), SUM(quantity) FROM {TABLE} "
                        "WHERE month BETWEEN ? AND ? GROUP BY month ORDER BY month", period)
        countries = query(f"SELECT COALESCE(country, 'Online'), SUM(sales_usd) FROM {TABLE} "
                          "WHERE month BETWEEN ? AND ? GROUP BY COALESCE(country, 'Online') ORDER BY 2 DESC", period)
        stores = query(f"SELECT COALESCE(store_name, 'Online / desconocida'), COALESCE(country, 'Online'), SUM(sales_usd), "
                       f"SUM(gross_profit_usd), SUM(quantity) FROM {TABLE} WHERE month BETWEEN ? AND ? "
                       "GROUP BY COALESCE(store_name, 'Online / desconocida'), COALESCE(country, 'Online') ORDER BY 3 DESC", period)
        detail = query(f"SELECT month, store_key, store_name, country, sales_usd, cost_usd, gross_profit_usd, quantity "
                       f"FROM {TABLE} WHERE month BETWEEN ? AND ? ORDER BY month, store_key", period)

    label = f"{period[0]:%m/%Y} – {latest:%m/%Y}"
    sales = sum(r[1] or 0 for r in monthly)
    profit = sum(r[2] or 0 for r in monthly)
    units = sum(r[3] or 0 for r in monthly)
    margin = profit / sales if sales else None  # margen total / ventas totales, nunca la media de márgenes

    report = Report.from_manifest(PROJECT, subtitle=label, kpi_columns=4, lang="es")
    report.add_kpi("Ventas netas", sales, format="currency", detail="USD")
    report.add_kpi("Margen bruto", profit, format="currency", detail="USD")
    report.add_kpi("Margen %", "Sin datos" if margin is None else f"{margin:.1%}", detail="Margen total / ventas totales")
    report.add_kpi("Unidades", units, format="integer")

    months = [f"{r[0]:%Y-%m}" for r in monthly]
    views = {
        "Ventas": [dict(x=months, y=[float(r[1]) for r in monthly], type="bar", name="Ventas", marker={"color": BLUE})],
        "Margen": [dict(x=months, y=[float(r[2]) for r in monthly], type="bar", name="Margen", marker={"color": ORANGE})],
        "Margen %": [dict(x=months, y=[float(100 * r[2] / r[1]) if r[1] else None for r in monthly], type="scatter",
                          mode="lines+markers", name="Margen %", line={"color": TEAL})],
    }
    report.add_chart(Chart("Evolución mensual", views["Ventas"], layout={"yaxis": {"title": "USD"}}, width="full",
                           views=views, view_layouts={"Margen %": {"yaxis": {"title": "%"}}}))
    report.add_chart(Chart.pie("Ventas por país", [r[0] for r in countries], [float(r[1]) for r in countries]))
    top = stores[:10][::-1]
    report.add_chart(Chart.bar("Top 10 tiendas por ventas | USD", [r[0] for r in top], [float(r[2]) for r in top], orientation="h"))
    report.add_table("Tiendas", ["Tienda", "País", "Ventas (USD)", "Margen (USD)", "Margen %", "Unidades"],
                     [[r[0], r[1], f"{r[2]:,.2f}", f"{r[3]:,.2f}", f"{r[3] / r[2]:.1%}" if r[2] else "Sin datos", f"{r[4]:,}"]
                      for r in stores],
                     source=TableSource(TABLE, "gold", ["month", "store_key"]), filters=["País"])
    report.add_link("Descargar Excel", "contoso-ventas-tiendas.xlsx")
    report.add_note(f"Periodo: {label}, meses completos. Fuente: {TABLE}. El último mes puede estar incompleto.")
    report.write(output)

    workbook = Workbook.from_manifest(PROJECT, subtitle=label)
    workbook.add_sheet("Tiendas", ["Tienda", "País", "Ventas", "Margen", "Margen %", "Unidades"],
                       [[r[0], r[1], r[2], r[3], (r[3] / r[2]) if r[2] else None, r[4]] for r in stores],
                       formats={"Ventas": "usd", "Margen": "usd", "Margen %": "percent"}, source=TABLE)
    workbook.add_sheet("Detalle mensual", ["Mes", "Id tienda", "Tienda", "País", "Ventas", "Coste", "Margen", "Unidades"],
                       detail, formats={"Mes": "month", "Ventas": "usd", "Coste": "usd", "Margen": "usd"}, source=TABLE)
    workbook.add_note("Margen % = margen total / ventas totales.")
    workbook.write(output / "contoso-ventas-tiendas.xlsx")
    print("Generated contoso-ventas-tiendas")  # nunca imprimir valores de datos


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    generate(parser.parse_args().output)

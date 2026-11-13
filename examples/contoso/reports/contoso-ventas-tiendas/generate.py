"""Contoso · Ventas por tienda: informe interactivo con barra de filtros + Excel.

La página lleva los datos mes × tienda de los últimos 36 meses. La barra de filtros
(periodo, país, tienda) recalcula en el navegador los KPIs, los gráficos y las tablas, y
cada botón Excel descarga lo que muestra su gráfico o tabla con esos filtros.

Lee gold.month_store (examples/contoso/01-crear-gold.sql). Construir con:
    sofibot build contoso-ventas-tiendas
"""
import argparse
from datetime import date
from pathlib import Path

from sofibot_eqz import Distinct, Gold, Ratio, Report, Sum, TableSource, Workbook

BLUE, ORANGE, CYAN, TEAL = "#2C3968", "#D16B1B", "#279CDB", "#5DAEAB"
PROJECT = Path(__file__).resolve().parent
TABLE = "gold.month_store"
MONTHS_IN_PAGE = 36   # meses que viajan dentro de la página (mes × tienda, agregados)
DEFAULT_MONTHS = 12   # periodo seleccionado al abrir el informe


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
        first = months_back(latest, MONTHS_IN_PAGE - 1)
        default = (months_back(latest, DEFAULT_MONTHS - 1), latest)
        rows = query(
            f"SELECT month, YEAR(month), store_key, COALESCE(store_name, 'Online / desconocida'), "
            f"COALESCE(country, 'Online'), sales_usd, cost_usd, gross_profit_usd, quantity FROM {TABLE} "
            "WHERE month BETWEEN ? AND ? ORDER BY month, store_key", [first, latest])

    columns = ["Mes", "Año", "Id tienda", "Tienda", "País", "Ventas", "Coste", "Margen", "Unidades"]
    usd = {"Ventas": "usd", "Coste": "usd", "Margen": "usd"}
    margin = Ratio("Margen", "Ventas")  # margen total / ventas totales, nunca la media de márgenes

    report = Report.from_manifest(PROJECT, subtitle=f"Datos de {first:%m/%Y} a {latest:%m/%Y}", kpi_columns=5, lang="es")
    report.add_dataset("ventas", columns, rows, formats={"Mes": "month", "Año": "text", **usd})

    report.add_filter("Periodo", "Mes", kind="range", default=default)
    report.add_filter("País", "País")
    report.add_filter("Tienda", "Tienda")

    report.add_dynamic_kpi("Ventas netas", "ventas", Sum("Ventas"), format="currency", detail="USD")
    report.add_dynamic_kpi("Margen bruto", "ventas", Sum("Margen"), format="currency", detail="USD")
    report.add_dynamic_kpi("Margen %", "ventas", margin, format="percent", detail="Margen total / ventas totales")
    report.add_dynamic_kpi("Unidades", "ventas", Sum("Unidades"), format="integer")
    report.add_dynamic_kpi("Tiendas con ventas", "ventas", Distinct("Id tienda"), format="integer")

    report.add_dynamic_chart("Evolución de ventas y margen | USD", "ventas", {"Mes": "Mes", "Año": "Año"},
                             [("Ventas", Sum("Ventas"), BLUE), ("Margen", Sum("Margen"), ORANGE)], width="full")
    report.add_dynamic_chart("Ventas por país | USD", "ventas", "País", [("Ventas", Sum("Ventas"), CYAN)],
                             kind="bar", order="desc")
    report.add_dynamic_chart("Margen % por mes", "ventas", "Mes", [("Margen %", Ratio("Margen", "Ventas", 100), TEAL)],
                             layout={"yaxis": {"ticksuffix": " %"}})
    report.add_dynamic_chart("Top 10 tiendas por ventas | USD", "ventas", "Tienda", [("Ventas", Sum("Ventas"), BLUE)],
                             kind="hbar", order="desc", top=10, width="full", height=460, layout={"margin": {"l": 190, "r": 25, "t": 40, "b": 45}})

    source = TableSource(TABLE, "gold", ["month", "store_key"])
    report.add_dynamic_table("Tiendas", "ventas", ["Tienda", "País"],
                             [("Ventas", Sum("Ventas"), "usd"), ("Margen", Sum("Margen"), "usd"),
                              ("Margen %", margin, "percent"), ("Unidades", Sum("Unidades"), "integer")],
                             filters=["País"], source=source)
    report.add_dynamic_table("Detalle mensual", "ventas", ["Mes", "Id tienda", "Tienda", "País", "Ventas", "Coste",
                                                           "Margen", "Unidades"], filters=["País"], source=source)

    label = f"{default[0]:%m/%Y} – {latest:%m/%Y}"
    report.add_link("Descargar Excel completo", "contoso-ventas-tiendas.xlsx")
    report.add_note(f"La página lleva {MONTHS_IN_PAGE} meses completos ({first:%m/%Y} – {latest:%m/%Y}); "
                    f"al abrirla se muestran los últimos {DEFAULT_MONTHS}. El último mes puede estar incompleto.")
    report.add_note("Los botones Excel de cada gráfico y tabla descargan lo que se ve con los filtros aplicados.")
    report.add_note(f"Fuente: {TABLE}. Margen % = margen total / ventas totales.")
    report.write(output)

    # Excel completo del informe: los últimos 12 meses, sin filtros.
    period = [row for row in rows if row[0] >= default[0]]
    stores: dict = {}
    for row in period:
        item = stores.setdefault((row[3], row[4]), [0, 0, 0])
        item[0] += row[5] or 0
        item[1] += row[7] or 0
        item[2] += row[8] or 0
    workbook = Workbook.from_manifest(PROJECT, subtitle=label)
    workbook.add_sheet("Tiendas", ["Tienda", "País", "Ventas", "Margen", "Margen %", "Unidades"],
                       sorted(([name, country, s, m, m / s if s else None, u] for (name, country), (s, m, u) in stores.items()),
                              key=lambda r: r[2], reverse=True),
                       formats={"Ventas": "usd", "Margen": "usd", "Margen %": "percent"}, source=TABLE)
    workbook.add_sheet("Detalle mensual", ["Mes", "Id tienda", "Tienda", "País", "Ventas", "Coste", "Margen", "Unidades"],
                       [[r[0], *r[2:]] for r in period], formats={"Mes": "month", **usd}, source=TABLE)
    workbook.add_note("Margen % = margen total / ventas totales.")
    workbook.write(output / "contoso-ventas-tiendas.xlsx")
    print("Generated contoso-ventas-tiendas")  # nunca imprimir valores de datos


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    generate(parser.parse_args().output)

"""Contoso · Productos (Excel): solo fichero Excel, varias hojas, sin página HTML.

Ejemplo de informe que entrega únicamente un .xlsx. Lee gold.month_product
(examples/contoso/01-crear-gold.sql). Construir con:
    sofibot build contoso-productos-excel
"""
import argparse
from datetime import date
from pathlib import Path

from sofibot_eqz import Gold, Workbook

PROJECT = Path(__file__).resolve().parent
TABLE = "gold.month_product"


def generate(output: Path) -> None:
    gold = Gold()
    with gold.connect() as con:
        latest = gold.query(f"SELECT MAX(month) FROM {TABLE}", connection=con)[1][0][0]
        if latest is None:
            raise ValueError(f"{TABLE} is empty")
        first = latest.year * 12 + latest.month - 1 - 11  # 12 meses completos hasta el último disponible
        period = [date(first // 12, first % 12 + 1, 1), latest]

        categories = gold.query(
            f"SELECT category AS Categoría, SUM(sales_usd) AS Ventas, SUM(gross_profit_usd) AS Margen, "
            f"SUM(gross_profit_usd) / NULLIF(SUM(sales_usd), 0) AS [Margen %], SUM(quantity) AS Unidades "
            f"FROM {TABLE} WHERE month BETWEEN ? AND ? GROUP BY category ORDER BY Ventas DESC", period, connection=con)
        ranking = gold.query(
            f"SELECT product_key AS [Id producto], product_name AS Producto, brand AS Marca, category AS Categoría, "
            f"subcategory AS Subcategoría, SUM(sales_usd) AS Ventas, SUM(gross_profit_usd) AS Margen, "
            f"SUM(gross_profit_usd) / NULLIF(SUM(sales_usd), 0) AS [Margen %], SUM(quantity) AS Unidades "
            f"FROM {TABLE} WHERE month BETWEEN ? AND ? "
            "GROUP BY product_key, product_name, brand, category, subcategory ORDER BY Ventas DESC", period, connection=con)
        detail = gold.query(
            f"SELECT month AS Mes, product_key AS [Id producto], product_name AS Producto, category AS Categoría, "
            f"sales_usd AS Ventas, cost_usd AS Coste, gross_profit_usd AS Margen, quantity AS Unidades "
            f"FROM {TABLE} WHERE month BETWEEN ? AND ? ORDER BY month, product_key", period, connection=con)

    money = {"Ventas": "usd", "Margen": "usd", "Margen %": "percent"}
    workbook = Workbook.from_manifest(PROJECT, subtitle=f"{period[0]:%m/%Y} – {latest:%m/%Y}")
    workbook.add_query("Categorías", categories, formats=money, source=TABLE)
    workbook.add_query("Ranking productos", ranking, formats=money, source=TABLE)
    workbook.add_query("Detalle mensual", detail, formats={"Mes": "month", "Ventas": "usd", "Coste": "usd", "Margen": "usd"},
                       source=TABLE)
    workbook.add_note("Importes en USD. Margen % = margen total / ventas totales.")
    workbook.write(output / "contoso-productos.xlsx")
    print("Generated contoso-productos-excel")  # nunca imprimir valores de datos


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    generate(parser.parse_args().output)

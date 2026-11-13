from datetime import date, datetime
from decimal import Decimal
import json
import re

import pytest

from sofibot_eqz import Chart, Report
from sofibot_eqz.html import display_value, excel_value


def payloads(html: str, kind: str) -> list[dict]:
    return [json.loads(text) for text in re.findall(rf'<script type="application/json" class="{kind}">(.*?)</script>', html)]


def test_cells_are_shown_formatted_and_keep_real_values_for_excel():
    report = Report("Informe", lang="es")
    report.add_table("Tiendas", ["Tienda", "Mes", "Ventas", "Margen %", "Unidades"],
                     [["Centro", date(2026, 1, 1), Decimal("1234.5"), 0.125, 1200],
                      ["Norte", date(2026, 2, 1), None, None, 3]],
                     formats={"Mes": "month", "Ventas": "eur", "Margen %": "percent"}, filters=["Tienda"])
    data = payloads(report.render(), "explorer-data")[0]
    assert data["kinds"] == [None, "month", "eur", "percent", "integer"]
    assert data["rows"][0] == ["Centro", "ene 2026", "1.234,50 €", "12,5 %", "1.200"]
    assert data["rows"][1][2:4] == ["", ""]
    assert data["values"] == {"1": [46023, 46054], "2": [1234.5, None], "3": [0.125, None], "4": [1200, 3]}


def test_every_table_and_chart_has_an_excel_button_unless_disabled():
    report = Report("Informe", lang="es")
    report.add_table("Interactiva", ["a"], [["x"]], filters=[])
    report.add_table("Estática", ["a"], [["x"]])
    report.add_table("Sin descarga", ["a"], [["x"]], download=False)
    report.add_chart(Chart.bar("Barras", ["x"], [1]))
    report.add_chart(Chart(title="Sin descarga", traces=[], download=False))
    html = report.render()
    assert html.count("data-download-table=") == 2
    assert html.count("data-download-chart=") == 1
    assert len(payloads(html, "table-data")) == 1  # the static table carries its rows for the download


def test_text_cells_are_kept_as_they_are():
    report = Report("Informe")
    report.add_table("T", ["Tienda", "Ventas"], [["A", "1,234.50"]], filters=[])
    data = payloads(report.render(), "explorer-data")[0]
    assert data["rows"] == [["A", "1,234.50"]] and data["values"] == {}


def test_display_and_excel_values():
    assert display_value(1234.5, "usd", "en") == "$1,234.50"
    assert display_value(datetime(2026, 1, 31, 14, 30), None, "es") == "31/01/2026 14:30"
    assert display_value(float("nan"), "number", "es") == ""
    assert excel_value(datetime(1900, 1, 1, 12)) == 2.5
    assert excel_value(True) == "True"


def test_invalid_tables_are_rejected():
    with pytest.raises(ValueError):
        Report("t").add_table("T", ["a"], [[1]], formats={"a": "pesetas"})
    with pytest.raises(ValueError):
        Report("t").add_table("T", ["a", "b"], [[1]])

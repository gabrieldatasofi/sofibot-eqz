from datetime import date
from decimal import Decimal
import json
import re

import pytest

from sofibot_eqz import Distinct, Ratio, Report, Sum


def report() -> Report:
    rows = [[date(2026, month, 1), store, country, Decimal(100 * month), Decimal(25 * month)]
            for month in (1, 2, 3) for store, country in (("Centro", "España"), ("Lyon", "Francia"))]
    page = Report("Informe", lang="es")
    page.add_dataset("v", ["Mes", "Tienda", "País", "Ventas", "Margen"], rows, formats={"Mes": "month", "Ventas": "eur"})
    page.add_filter("Periodo", "Mes", kind="range", default=(date(2026, 2, 1), date(2026, 3, 1)))
    page.add_filter("País", "País", default="Francia")
    return page


def spec(html: str) -> dict:
    return json.loads(re.search(r"window\.REPORT_DYNAMIC=(.*?);\nfunction grouped", html).group(1))


def test_kpis_are_computed_with_the_default_filters():
    page = report()
    page.add_dynamic_kpi("Ventas", "v", Sum("Ventas"), format="eur")
    page.add_dynamic_kpi("Margen %", "v", Ratio("Margen", "Ventas"), format="percent")
    page.add_dynamic_kpi("Tiendas", "v", Distinct("Tienda"), format="integer")
    html = page.render()
    # Lyon, February and March: 200 + 300
    assert "500 €" in html and "25,0 %" in html
    assert re.search(r'data-dynamic-kpi="2"><span>Tiendas</span><div class="kpi-value"><strong>1<', html)


def test_filter_bar_lists_options_with_labels_and_defaults():
    html = report().render()
    assert 'class="panel filters"' in html
    assert ">ene 2026</option>" in html and ">Francia</option>" in html
    period = re.findall(r'<select data-filter="0" data-default="(\d+)" data-all="(\d+)">', html)
    assert period == [("1", "0"), ("2", "2")]


def test_dynamic_table_is_sent_to_the_page_with_kinds_and_headers():
    page = report()
    page.add_dynamic_table("Tiendas", "v", ["Tienda", "País"], [("Ventas", Sum("Ventas"), "eur"),
                                                                 ("Margen %", Ratio("Margen", "Ventas"), "percent")],
                           headers={"Tienda": "Nombre"}, filters=["País"])
    page.add_dynamic_table("Detalle", "v", ["Mes", "Tienda", "Ventas"])
    html = page.render()
    tables = spec(html)["tables"]
    assert tables[0]["headers"] == ["Nombre", "País", "Ventas", "Margen %"]
    assert tables[0]["kinds"] == [None, None, "eur", "percent"]
    assert tables[1]["kinds"] == ["month", None, "eur"] and tables[1]["measures"] == []
    assert html.count("data-download-table=") == 2


def test_dynamic_chart_first_render_and_download_button():
    page = report()
    page.add_dynamic_chart("Evolución", "v", "Mes", [("Ventas", Sum("Ventas"))])
    html = page.render()
    charts = json.loads(re.search(r"const charts=(.*?);const labels", html).group(1))
    assert charts[0]["traces"][0]["x"] == ["feb 2026", "mar 2026"] and charts[0]["traces"][0]["y"] == [200.0, 300.0]
    assert charts[0]["category"] == "Mes" and 'data-download-chart="chart-0"' in html


def test_sum_without_values_is_no_data_not_zero():
    page = Report("t", lang="es")
    page.add_dataset("v", ["País", "Ventas"], [["España", None]])
    page.add_dynamic_kpi("Ventas", "v", Sum("Ventas"), format="eur")
    assert "<strong>—</strong>" in page.render()


def test_invalid_definitions_are_rejected():
    page = report()
    with pytest.raises(ValueError):
        page.add_dynamic_kpi("x", "otro", Sum("Ventas"))
    with pytest.raises(ValueError):
        page.add_dynamic_kpi("x", "v", Sum("Coste"))
    with pytest.raises(ValueError):
        page.add_dynamic_table("x", "v", ["Tienda"], [("Ventas", Sum("Ventas"))])  # no format
    with pytest.raises(ValueError):
        page.add_dynamic_table("x", "v", ["Tienda"], [("Δ", Sum("Ventas").vs_previous(), "percent")])
    with pytest.raises(ValueError):
        page.add_filter("x", "Coste")
    with pytest.raises(ValueError):
        page.add_dataset("v", ["a"], [[1]])

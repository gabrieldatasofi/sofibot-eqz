from datetime import date
from decimal import Decimal
import zipfile

import pytest

from sofibot_eqz import Workbook


def test_workbook_has_info_sheet_and_one_table_per_sheet(tmp_path):
    workbook = Workbook("Prueba", "Descripción")
    workbook.add_sheet("Ventas", ["Mes", "Ventas", "Margen %"],
                       [[date(2026, 1, 1), Decimal("10.50"), 0.25], [date(2026, 2, 1), None, None]],
                       formats={"Mes": "month", "Ventas": "eur", "Margen %": "percent"}, source="gold.x")
    workbook.add_query("Detalle", (["Id", "Nombre"], [(1, "a"), (2, "b")]))
    with zipfile.ZipFile(workbook.write(tmp_path / "out.xlsx")) as book:
        names = book.namelist()
    assert {"xl/worksheets/sheet1.xml", "xl/worksheets/sheet3.xml", "xl/tables/table2.xml"} <= set(names)


def test_formats_are_inferred_from_values():
    sheet = Workbook("t").add_sheet("A", ["d", "n", "i", "s"], [[date(2026, 1, 1), Decimal("1.5"), 3, "x"]]).sheets[0]
    assert sheet.formats == {"d": "date", "n": "number", "i": "integer"}


def test_invalid_input_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        Workbook("t").add_sheet("A", ["x"], [[1]], formats={"x": "pesetas"})
    with pytest.raises(ValueError):
        Workbook("t").add_sheet("Info", ["x"], [[1]])
    with pytest.raises(ValueError):
        Workbook("t").add_sheet("A", ["x", "y"], [[1]]).write(tmp_path / "bad.xlsx")

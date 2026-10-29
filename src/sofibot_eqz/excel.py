"""Excel workbooks in Datasofi style: an Info sheet plus one filterable Excel table per sheet."""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import re
from typing import Any, Iterable

import xlsxwriter

BLUE = "#2C3968"
FORMATS = {
    "eur": "#,##0.00 [$€-es-ES]",
    "usd": "[$$-en-US]#,##0.00",
    "percent": "0.0%",  # 0.25 is shown as 25.0%
    "integer": "#,##0",
    "number": "#,##0.00",
    "date": "dd/mm/yyyy",
    "datetime": "dd/mm/yyyy hh:mm",
    "month": "mmm yyyy",
    "text": "@",
}
FORMATS["currency"] = FORMATS["eur"]
EXCEL_MAX_ROWS = 1_048_575  # plus the header row
WIDTH_SAMPLE_ROWS = 500


def infer_format(values: Iterable[Any]) -> str | None:
    """Format for a column from its first non-empty value: dates, integers and decimals."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return None
        if isinstance(value, datetime):
            return "datetime"
        if isinstance(value, date):
            return "date"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, (float, Decimal)):
            return "number"
        return None
    return None


@dataclass
class Sheet:
    name: str
    columns: list[str]
    rows: list[list[Any]]
    formats: dict[str, str] = field(default_factory=dict)
    source: str = ""


class Workbook:
    def __init__(self, title: str, description: str = "", subtitle: str = "") -> None:
        self.title = title
        self.description = description
        self.subtitle = subtitle
        self.sheets: list[Sheet] = []
        self.notes: list[str] = []

    @classmethod
    def from_manifest(cls, project_dir: Path, *, subtitle: str = "") -> "Workbook":
        manifest = json.loads((Path(project_dir) / "report.json").read_text(encoding="utf-8"))
        return cls(manifest["name"], manifest.get("description", ""), subtitle)

    def add_sheet(
        self,
        name: str,
        columns: Iterable[str],
        rows: Iterable[Iterable[Any]],
        *,
        formats: dict[str, str] | None = None,
        source: str = "",
    ) -> "Workbook":
        """Add a sheet with one Excel table. Pass real numbers and dates, not formatted text.

        `formats` maps column names to a key of FORMATS (eur, usd, percent, integer, number,
        date, datetime, month, text); columns left out get one from their values."""
        columns = [str(column) for column in columns]
        if len(set(columns)) != len(columns) or not all(columns):
            raise ValueError("Column names must be unique and non-empty")
        rows = [list(row) for row in rows]
        if len(rows) > EXCEL_MAX_ROWS:
            raise ValueError(f"Sheet {name}: {len(rows):,} rows exceed Excel's limit; filter or split the data")
        formats = dict(formats or {})
        unknown = [key for key in formats if key not in columns]
        bad = [value for value in formats.values() if value not in FORMATS]
        if unknown or bad:
            raise ValueError(f"Invalid formats: unknown columns {unknown}, unknown formats {bad}")
        for index, column in enumerate(columns):
            if column not in formats and (kind := infer_format(row[index] for row in rows if len(row) == len(columns))):
                formats[column] = kind
        name = re.sub(r"[\[\]:*?/\\]", "-", name)[:31]
        if name.casefold() in {sheet.name.casefold() for sheet in self.sheets} | {"info"}:
            raise ValueError(f"Duplicate sheet name: {name}")
        self.sheets.append(Sheet(name, columns, rows, formats, source))
        return self

    def add_query(self, name: str, result: tuple[list[str], list[tuple]], *, formats: dict[str, str] | None = None,
                  source: str = "") -> "Workbook":
        """Add the (columns, rows) returned by Gold.query() as a sheet."""
        columns, rows = result
        return self.add_sheet(name, columns, rows, formats=formats, source=source)

    def add_dataframe(self, name: str, frame, *, formats: dict[str, str] | None = None, source: str = "") -> "Workbook":
        return self.add_sheet(name, list(frame.columns), frame.itertuples(index=False, name=None),
                              formats=formats, source=source)

    def add_note(self, text: str) -> "Workbook":
        self.notes.append(text)
        return self

    def write(self, path: Path) -> Path:
        if not self.sheets:
            raise ValueError("The workbook has no sheets")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        book = xlsxwriter.Workbook(str(path), {"strings_to_numbers": False, "strings_to_formulas": False,
                                               "strings_to_urls": False, "remove_timezone": True})
        book.set_properties({"title": self.title, "subject": self.description, "company": "Datasofi"})
        styles = {key: book.add_format({"num_format": value, "font_name": "Roboto"}) for key, value in FORMATS.items()}
        styles[None] = book.add_format({"font_name": "Roboto"})
        header = book.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": BLUE, "font_name": "Roboto"})
        self._write_info(book)
        for sheet in self.sheets:
            self._write_sheet(book, sheet, styles, header)
        book.close()
        return path

    def _write_info(self, book) -> None:
        info = book.add_worksheet("Info")
        info.hide_gridlines(2)
        info.set_column(0, 0, 24)
        info.set_column(1, 1, 90)
        title = book.add_format({"bold": True, "font_size": 18, "font_color": BLUE, "font_name": "Roboto"})
        label = book.add_format({"bold": True, "font_color": BLUE, "font_name": "Roboto", "valign": "top"})
        text = book.add_format({"text_wrap": True, "font_name": "Roboto", "valign": "top"})
        info.write(0, 0, self.title, title)
        details = [("Descripción", self.description), ("Periodo", self.subtitle),
                   ("Generado", datetime.now().astimezone().strftime("%d/%m/%Y %H:%M %Z"))]
        details += [(f"Hoja «{sheet.name}»", f"{len(sheet.rows):,} filas" + (f" · fuente {sheet.source}" if sheet.source else ""))
                    for sheet in self.sheets]
        details += [("Notas" if index == 0 else "", note) for index, note in enumerate(self.notes)]
        row = 2
        for key, value in details:
            if value:
                info.write_string(row, 0, key, label)
                info.write_string(row, 1, str(value), text)
                row += 1

    @staticmethod
    def _write_sheet(book, sheet: Sheet, styles: dict, header) -> None:
        worksheet = book.add_worksheet(sheet.name)
        kinds = [sheet.formats.get(column) for column in sheet.columns]
        for row_index, row in enumerate(sheet.rows, start=1):
            if len(row) != len(sheet.columns):
                raise ValueError(f"Sheet {sheet.name}: row {row_index} has {len(row)} values, expected {len(sheet.columns)}")
            for column_index, value in enumerate(row):
                style = styles[kinds[column_index]]
                if value is None:
                    worksheet.write_blank(row_index, column_index, None, style)
                elif isinstance(value, bool):
                    worksheet.write_boolean(row_index, column_index, value, style)
                elif isinstance(value, (int, float, Decimal)):
                    worksheet.write_number(row_index, column_index, float(value), style)
                elif isinstance(value, (date, datetime)):
                    worksheet.write_datetime(row_index, column_index, value,
                                             style if kinds[column_index] else styles["date"])
                else:
                    worksheet.write_string(row_index, column_index, str(value), style)
        worksheet.add_table(0, 0, max(len(sheet.rows), 1), len(sheet.columns) - 1, {
            "name": "t_" + re.sub(r"\W", "_", sheet.name, flags=re.ASCII),
            "style": "Table Style Medium 2",
            "columns": [{"header": column, "header_format": header} for column in sheet.columns],
        })
        worksheet.freeze_panes(1, 0)
        for column_index, column in enumerate(sheet.columns):
            sample = [row[column_index] for row in sheet.rows[:WIDTH_SAMPLE_ROWS]]
            longest = max([len(column) + 4] + [len(f"{v:,.2f}" if isinstance(v, (int, float, Decimal)) else str(v))
                                                for v in sample if v is not None and not isinstance(v, bool)])
            worksheet.set_column(column_index, column_index, min(max(longest + 2, 10), 60))

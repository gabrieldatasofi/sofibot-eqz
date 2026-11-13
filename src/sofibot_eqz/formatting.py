"""Cell formatting shared by the HTML page and the Excel downloads (keys of excel.FORMATS)."""
from datetime import date, datetime
from decimal import Decimal
import math
from typing import Any

MONTHS = {"es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"],
          "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
EXCEL_EPOCH = datetime(1899, 12, 30)


def grouped(value: float, decimals: int, lang: str) -> str:
    text = f"{value:,.{decimals}f}"
    return text.translate(str.maketrans(",.", ".,")) if lang == "es" else text


def display_value(value: Any, kind: str | None, lang: str) -> str:
    """Text shown in an HTML table cell for a value and its format (the keys of excel.FORMATS)."""
    if value is None:
        return ""
    if isinstance(value, str) or isinstance(value, bool) or kind == "text":
        return str(value)
    if isinstance(value, (date, datetime)):
        if kind == "month":
            return f"{MONTHS[lang][value.month - 1]} {value.year}"
        if isinstance(value, datetime) and kind != "date":
            return value.strftime("%d/%m/%Y %H:%M")
        return value.strftime("%d/%m/%Y")
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        if not math.isfinite(number):
            return ""
        if kind == "percent":
            return grouped(number * 100, 1, lang) + (" %" if lang == "es" else "%")
        if kind in ("eur", "currency"):
            return grouped(number, 2, lang) + " €" if lang == "es" else "€" + grouped(number, 2, lang)
        if kind == "usd":
            return "$" + grouped(number, 2, lang)
        if kind == "integer" or (kind is None and isinstance(value, int)):
            return grouped(number, 0, lang)
        return grouped(number, 2, lang)
    return str(value)


def excel_value(value: Any) -> Any:
    """Value for the Excel download: numbers, dates as Excel serial numbers, text or None."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, datetime):
        return (value.replace(tzinfo=None) - EXCEL_EPOCH).total_seconds() / 86400
    if isinstance(value, date):
        return (value - EXCEL_EPOCH.date()).days
    return str(value)

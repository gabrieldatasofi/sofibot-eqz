"""Sofibot for Equivalenza: HTML reports and Excel files from SQL Server Gold tables."""
from . import config  # noqa: F401  loads .env before anything reads the settings
from .db import Gold, Settings
from .dynamic import Distinct, Ratio, Sum
from .excel import Workbook
from .html import Chart, KPI, Report, Table, TableSource

__version__ = "0.2.3"
__all__ = ["Chart", "Distinct", "Gold", "KPI", "Ratio", "Report", "Settings", "Sum", "Table", "TableSource", "Workbook"]

"""Sofibot for Equivalenza: HTML reports and Excel files from SQL Server Gold tables."""
from . import config  # noqa: F401  loads .env before anything reads the settings
from .db import Gold, Settings
from .excel import Workbook
from .html import Chart, KPI, Report, Table, TableSource

__version__ = "0.1.0"
__all__ = ["Chart", "Gold", "KPI", "Report", "Settings", "Table", "TableSource", "Workbook"]

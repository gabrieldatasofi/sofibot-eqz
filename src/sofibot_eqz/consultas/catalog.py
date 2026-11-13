"""Semantic catalog: what may be asked of each Gold table (reports/catalogo.json).

    {"tables": {"gold.ventas_mes_tienda": {
        "description": "Ventas mensuales por tienda, en euros sin IVA",
        "period": "mes",
        "dimensions": {"mes": {"column": "mes", "description": "Mes"},
                       "tienda": {"column": "tienda", "synonyms": ["local"]}},
        "measures": {"ventas": {"sum": "ventas_eur", "format": "eur", "synonyms": ["facturación"]},
                     "margen_pct": {"ratio": ["margen_eur", "ventas_eur"], "format": "percent"},
                     "tiendas": {"distinct": "tienda", "format": "integer"}},
        "rules": ["No sumar con gold.ventas_mes_producto: describen las mismas ventas"]}}}

A measure is a sum, a ratio of two sums (never an average of stored ratios) or a count of
distinct values. Names are lowercase identifiers; columns must exist in the schema contract
(`sofibot catalog` checks it). The catalog holds names and descriptions, never data.
"""
import json
from pathlib import Path
import re

from .. import config

NAME = re.compile(r"[a-z][a-z0-9_]{0,62}")
COLUMN = re.compile(r"\w{1,128}")
TABLE = re.compile(r"\w{1,128}\.\w{1,128}")
FORMATS = {"eur", "usd", "currency", "integer", "number", "percent", "date", "month", "text"}
KINDS = ("sum", "ratio", "distinct")


class CatalogError(Exception):
    pass


def catalog_file() -> Path:
    return config.REPORTS_DIR / "catalogo.json"


def _texts(value, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CatalogError(f"{where}: must be a list of texts")
    return value


def _entry(value, where: str) -> dict:
    if not isinstance(value, dict):
        raise CatalogError(f"{where}: must be an object")
    return value


def load(path: Path | None = None) -> dict:
    """The validated catalog: table (lower case) -> {description, period, dimensions, measures, rules}."""
    path = path or catalog_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"{path.name} does not exist (docs/11-consultas.md)") from exc
    except (OSError, ValueError) as exc:
        raise CatalogError(f"{path.name}: {exc}") from exc
    tables = _entry(data, path.name).get("tables")
    if not isinstance(tables, dict) or not tables:
        raise CatalogError(f'{path.name}: expected {{"tables": {{"gold.<table>": {{...}}}}}}')
    catalog = {}
    for table, spec in tables.items():
        where = f"{path.name}, {table}"
        if not isinstance(table, str) or not TABLE.fullmatch(table):
            raise CatalogError(f"{where}: the table must be schema.table")
        spec = _entry(spec, where)
        period = spec.get("period")
        if period is not None and (not isinstance(period, str) or not COLUMN.fullmatch(period)):
            raise CatalogError(f"{where}: period must be a column name")
        dimensions = {}
        for name, dim in _entry(spec.get("dimensions", {}), f"{where}, dimensions").items():
            dim = _entry(dim, f"{where}, dimension {name}")
            if not NAME.fullmatch(name) or not COLUMN.fullmatch(str(dim.get("column", ""))):
                raise CatalogError(f"{where}, dimension {name}: lowercase name and a 'column' are required")
            dimensions[name] = {"column": dim["column"], "description": str(dim.get("description", "")),
                                "synonyms": _texts(dim.get("synonyms"), f"{where}, dimension {name}")}
        measures = {}
        for name, measure in _entry(spec.get("measures", {}), f"{where}, measures").items():
            measure = _entry(measure, f"{where}, measure {name}")
            kinds = [kind for kind in KINDS if kind in measure]
            if not NAME.fullmatch(name) or len(kinds) != 1:
                raise CatalogError(f"{where}, measure {name}: lowercase name and exactly one of sum, ratio, distinct")
            kind = kinds[0]
            columns = measure[kind] if kind == "ratio" else [measure[kind]]
            if (not isinstance(columns, list) or len(columns) != (2 if kind == "ratio" else 1)
                    or not all(isinstance(c, str) and COLUMN.fullmatch(c) for c in columns)):
                raise CatalogError(f"{where}, measure {name}: {kind} needs "
                                   f"{'[numerator, denominator] columns' if kind == 'ratio' else 'a column'}")
            fmt = measure.get("format", "number")
            if fmt not in FORMATS:
                raise CatalogError(f"{where}, measure {name}: format must be one of {', '.join(sorted(FORMATS))}")
            scale = measure.get("scale", 1)
            if not isinstance(scale, (int, float)) or isinstance(scale, bool):
                raise CatalogError(f"{where}, measure {name}: scale must be a number")
            measures[name] = {"kind": kind, "columns": columns, "format": fmt, "scale": scale,
                              "description": str(measure.get("description", "")),
                              "synonyms": _texts(measure.get("synonyms"), f"{where}, measure {name}")}
        if not measures:
            raise CatalogError(f"{where}: at least one measure is required")
        if names := set(dimensions) & set(measures):
            raise CatalogError(f"{where}: {', '.join(sorted(names))} is both a dimension and a measure")
        catalog[table.casefold()] = {"description": str(spec.get("description", "")), "period": period,
                                     "dimensions": dimensions, "measures": measures,
                                     "rules": _texts(spec.get("rules"), f"{where}, rules")}
    return catalog


def problems_against(catalog: dict, contract: dict) -> list[str]:
    """Tables and columns of the catalog missing from the schema contract (gold_schema.json)."""
    known = {name.casefold(): {c["name"].casefold() for c in spec.get("columns", [])}
             for name, spec in contract.get("tables", {}).items()}
    problems = []
    for table, spec in catalog.items():
        if table not in known:
            problems.append(f"{table}: not in the schema contract")
            continue
        used = {spec["period"]} if spec["period"] else set()
        used |= {d["column"] for d in spec["dimensions"].values()}
        used |= {c for m in spec["measures"].values() for c in m["columns"]}
        problems += [f"{table}: column {column} not in the schema contract"
                     for column in sorted(used) if column.casefold() not in known[table]]
    return problems


def for_tables(catalog: dict, tables: set[str] | None) -> dict:
    """What a user may ask: only the tables their roles allow (None = all). No column names."""
    visible = {}
    for table, spec in catalog.items():
        if tables is not None and table not in tables:
            continue
        visible[table] = {
            "description": spec["description"], "has_period": bool(spec["period"]),
            "dimensions": {n: {"description": d["description"], "synonyms": d["synonyms"]} for n, d in spec["dimensions"].items()},
            "measures": {n: {"kind": m["kind"], "format": m["format"], "description": m["description"],
                             "synonyms": m["synonyms"]} for n, m in spec["measures"].items()},
            "rules": spec["rules"],
        }
    return visible

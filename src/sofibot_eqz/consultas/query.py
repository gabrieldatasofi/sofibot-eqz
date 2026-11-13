"""A structured query (measures by dimensions, filters, period) turned into parameterized SQL.

The caller names catalog entries only; every identifier in the SQL comes from the catalog
(validated names, quoted with []) and every value travels as a `?` parameter. Ratios are
sum / sum. Whole calendar months: period {"from": "2026-01", "to": "2026-03"} includes March.
"""
from datetime import date, datetime
from decimal import Decimal
import re

from pydantic import BaseModel, ConfigDict, Field

MONTH = re.compile(r"(\d{4})-(\d{2})")


class QueryError(Exception):
    """A request the catalog does not allow. The message is safe to return."""


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension: str
    values: list[str | int | float] = Field(min_length=1, max_length=100)


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    start: str = Field(alias="from")
    end: str = Field(alias="to")


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: str
    desc: bool = True


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    measures: list[str] = Field(min_length=1, max_length=10)
    dimensions: list[str] = Field(default_factory=list, max_length=5)
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    period: Period | None = None
    order: Order | None = None
    limit: int | None = Field(default=None, ge=1)
    question_id: str | None = Field(default=None, max_length=64)


def _month(value: str) -> date:
    match = MONTH.fullmatch(value or "")
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise QueryError(f"Months are YYYY-MM, not '{value}'")
    return date(int(match.group(1)), int(match.group(2)), 1)


def _next_month(value: date) -> date:
    return date(value.year + value.month // 12, value.month % 12 + 1, 1)


def _quoted(identifier: str) -> str:
    return "[" + identifier.replace("]", "]]") + "]"


def build(catalog: dict, request: QueryRequest, max_rows: int) -> tuple[str, list, list[str]]:
    """SQL, parameters and result column names. Fetches max one row more than the limit, to tell truncation."""
    table = request.table.casefold()
    spec = catalog.get(table)
    if spec is None:
        raise QueryError(f"'{request.table}' is not in your catalog")
    dims, measures = spec["dimensions"], spec["measures"]
    for name in request.dimensions:
        if name not in dims:
            raise QueryError(f"'{name}' is not a dimension of {table}")
    for name in request.measures:
        if name not in measures:
            raise QueryError(f"'{name}' is not a measure of {table}")
    if len(set(request.dimensions)) != len(request.dimensions) or len(set(request.measures)) != len(request.measures):
        raise QueryError("Each dimension and measure can appear only once")
    limit = min(request.limit or max_rows, max_rows)
    params: list = [limit + 1]
    select = [f"{_quoted(dims[name]['column'])} AS {_quoted(name)}" for name in request.dimensions]
    for name in request.measures:
        measure = measures[name]
        columns = [_quoted(c) for c in measure["columns"]]
        if measure["kind"] == "sum":
            expression = f"SUM({columns[0]})"
        elif measure["kind"] == "distinct":
            expression = f"COUNT(DISTINCT {columns[0]})"
        else:
            expression = f"CAST(SUM({columns[0]}) AS decimal(38, 10)) / NULLIF(SUM({columns[1]}), 0)"
        if measure["scale"] != 1:
            expression = f"({expression}) * {float(measure['scale'])!r}"
        select.append(f"{expression} AS {_quoted(name)}")
    where = []
    if request.period is not None:
        if not spec["period"]:
            raise QueryError(f"{table} has no period column")
        start, end = _month(request.period.start), _month(request.period.end)
        if start > end:
            raise QueryError("The period starts after it ends")
        where.append(f"{_quoted(spec['period'])} >= ? AND {_quoted(spec['period'])} < ?")
        params += [start, _next_month(end)]
    for item in request.filters:
        if item.dimension not in dims:
            raise QueryError(f"'{item.dimension}' is not a dimension of {table}")
        where.append(f"{_quoted(dims[item.dimension]['column'])} IN ({', '.join('?' * len(item.values))})")
        params += item.values
    schema, name = table.split(".")
    sql = f"SELECT TOP (?) {', '.join(select)} FROM {_quoted(schema)}.{_quoted(name)}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if request.dimensions:
        sql += " GROUP BY " + ", ".join(_quoted(dims[n]["column"]) for n in request.dimensions)
    order = request.order
    if order is not None:
        if order.by not in request.dimensions and order.by not in request.measures:
            raise QueryError("order.by must be one of the requested dimensions or measures")
        sql += f" ORDER BY {_quoted(order.by)} {'DESC' if order.desc else 'ASC'}"
    elif request.dimensions:
        sql += " ORDER BY " + ", ".join(_quoted(n) for n in request.dimensions)
    return sql, params, [*request.dimensions, *request.measures]


def plain(value):
    """JSON-friendly value: numbers stay numbers, dates become ISO text, NULL stays null (no data)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value

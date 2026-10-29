"""Gold schema contract: tables, views, columns, types and descriptions. Never reads rows.

Report authors (people or AI assistants) work from this contract, not from the data.
Descriptions come from the MS_Description extended properties, so documenting a table or
column in SQL Server documents it here (docs/03-tablas-gold.md).
"""
from datetime import datetime, timezone

from .db import Gold

COLUMNS_SQL = """
SELECT o.name, o.type, CAST(od.value AS nvarchar(4000)), c.name, ty.name, c.max_length, c.precision, c.scale,
       c.is_nullable, CAST(cd.value AS nvarchar(4000))
FROM sys.objects o
JOIN sys.columns c ON c.object_id = o.object_id
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
LEFT JOIN sys.extended_properties od
       ON od.class = 1 AND od.major_id = o.object_id AND od.minor_id = 0 AND od.name = 'MS_Description'
LEFT JOIN sys.extended_properties cd
       ON cd.class = 1 AND cd.major_id = o.object_id AND cd.minor_id = c.column_id AND cd.name = 'MS_Description'
WHERE o.schema_id = SCHEMA_ID(?) AND o.type IN ('U', 'V')
ORDER BY o.name, c.column_id
"""


def _type_name(name: str, max_length: int, precision: int, scale: int) -> str:
    if name in {"decimal", "numeric"}:
        return f"{name}({precision},{scale})"
    if name in {"varchar", "char", "varbinary", "binary"}:
        return f"{name}({'max' if max_length == -1 else max_length})"
    if name in {"nvarchar", "nchar"}:
        return f"{name}({'max' if max_length == -1 else max_length // 2})"
    return name


def describe(gold: Gold | None = None) -> dict:
    gold = gold or Gold()
    schema = gold.settings.schema
    _, rows = gold.query(COLUMNS_SQL, [schema])
    tables: dict[str, dict] = {}
    for name, kind, table_description, column, type_name, max_length, precision, scale, nullable, description in rows:
        entry = tables.setdefault(f"{schema}.{name}", {
            "type": "view" if kind.strip() == "V" else "table", "description": table_description or "", "columns": [],
        })
        entry["columns"].append({
            "name": column, "type": _type_name(type_name, max_length, precision, scale),
            "nullable": bool(nullable), "description": description or "",
        })
    return {
        "source": "SQL Server", "database": gold.settings.database, "schema": schema,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Structure only. It contains no rows, counts or values.",
        "tables": tables,
    }

# 03 · Tablas Gold

Sofibot lee un único esquema de vuestro warehouse (por defecto `gold`, configurable con
`SQLSERVER_GOLD_SCHEMA`). En él pueden estar **tablas o vistas**. Sofibot no transforma
datos: las tablas Gold ya deben estar limpias y agregadas para reporting.

## Recomendaciones para las tablas Gold

| Recomendación | Por qué |
|---|---|
| Una fila por un **grano** claro (por ejemplo mes × tienda, día × producto) y documentado | Evita sumar dos veces y hace los informes predecibles |
| Fechas como `date` (no texto) y meses como el primer día del mes | Permite filtrar por periodos y que Excel las trate como fechas |
| Importes en `decimal(19,2)` (no `float`) e indicando moneda e impuestos en la descripción | Totales exactos y sin ambigüedad (con o sin IVA) |
| Incluir los nombres además de los códigos (tienda, producto, familia) | Los informes muestran nombres sin necesitar acceso a otras tablas |
| Índice o clave por las columnas de fecha y de dimensión | Consultas rápidas por periodo |
| Nombres de columna estables | Cambiar un nombre rompe los informes que lo usan |
| Si hay tablas grandes de detalle, ofrecer también tablas o vistas agregadas | Los informes cargan sus datos en memoria |

## Documentar tablas y columnas

Sofibot recoge las descripciones de SQL Server (propiedad `MS_Description`) y las incluye
en el contrato de esquema. Es la mejor forma de que quien escriba los informes sepa qué
significa cada columna. En SSMS se editan en el diseñador de la tabla, o con T-SQL:

```sql
EXEC sp_addextendedproperty N'MS_Description', N'Ventas por mes y tienda. Una fila por mes y tienda_id.',
     N'SCHEMA', N'gold', N'TABLE', N'ventas_mes_tienda';

EXEC sp_addextendedproperty N'MS_Description', N'Venta neta sin IVA, en euros.',
     N'SCHEMA', N'gold', N'TABLE', N'ventas_mes_tienda', N'COLUMN', N'ventas_eur';
```

Para cambiar una descripción existente se usa `sp_updateextendedproperty` con los mismos argumentos.
Si se ejecutan desde un fichero con `sqlcmd`, añadir `-f 65001`: sin él, los acentos de las
descripciones se guardan mal ("dÃ­a" en vez de "día").

Conviene documentar en especial:

- el **grano** de cada tabla (qué representa una fila);
- la **moneda** y si los importes llevan impuestos;
- las columnas que **no se pueden sumar** (por ejemplo clientes distintos o tickets si un
  ticket puede aparecer en varias filas);
- qué significa un valor `NULL`.

## El contrato de esquema: `reports/gold_schema.json`

```bash
docker compose run --rm sofibot sofibot schema
```

Genera un JSON con la estructura del esquema Gold, consultando solo el catálogo de SQL
Server (`sys.objects`, `sys.columns`, `sys.extended_properties`). **No contiene filas,
recuentos ni valores**:

```json
{
  "source": "SQL Server",
  "database": "NombreDelWarehouse",
  "schema": "gold",
  "tables": {
    "gold.ventas_mes_tienda": {
      "type": "table",
      "description": "Ventas por mes y tienda. Una fila por mes y tienda_id.",
      "columns": [
        {"name": "mes", "type": "date", "nullable": false, "description": "Primer día del mes natural."},
        {"name": "ventas_eur", "type": "decimal(19,2)", "nullable": false, "description": "Venta neta sin IVA, en euros."}
      ]
    }
  }
}
```

Es la referencia para escribir informes, tanto para personas como para asistentes de IA,
que pueden trabajar solo con este fichero sin ver datos (ver [06 · Seguridad](06-seguridad.md)).
Regeneradlo cada vez que cambien las tablas Gold y guardadlo junto a los informes.

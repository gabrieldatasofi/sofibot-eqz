# 04 · Crear informes

Cada informe es una carpeta dentro de `reports/` con dos ficheros:

```
reports/
├── gold_schema.json              estructura de las tablas Gold (sofibot schema)
└── ventas-tiendas/               un proyecto de informe; el nombre de la carpeta es su "slug"
    ├── report.json               nombre y descripción que se ven en el portal
    └── generate.py               consultas a Gold y contenido del informe (Python)
```

`sofibot build ventas-tiendas` ejecuta `generate.py` y deja el resultado en
`output/ventas-tiendas/`:

```
output/ventas-tiendas/
├── index.html                    página del informe (con gráficos y tablas interactivas)
├── ventas-tiendas.xlsx           fichero Excel, descargable desde el portal y desde la página
└── assets/, plotly.min.js        tipografías y librería de gráficos (funciona sin internet)
```

Un informe puede generar **solo la página**, **solo el Excel** o **las dos cosas**.

## 1. Crear el proyecto

```bash
docker compose run --rm sofibot sofibot new ventas-tiendas \
    --name "Ventas por tienda" --table gold.ventas_mes_tienda \
    --description "Ventas y margen de los últimos 12 meses por tienda"
```

- `slug` (`ventas-tiendas`): minúsculas, números y guiones. Es el nombre de la carpeta y de la URL.
- `--table`: la tabla Gold principal del informe.

El proyecto creado **funciona sin tocar nada**: exporta la tabla completa a una página con
tabla filtrable y a un Excel. Pruébalo:

```bash
docker compose run --rm sofibot sofibot build ventas-tiendas
```

Después se edita `generate.py` para darle el contenido que se quiera.

## 2. Estructura de `generate.py`

```python
from sofibot_eqz import Chart, Gold, Report, TableSource, Workbook

PROJECT = Path(__file__).resolve().parent
TABLE = "gold.ventas_mes_tienda"


def generate(output: Path) -> None:
    gold = Gold()
    with gold.connect() as con:                                       # 1. leer de Gold
        columns, rows = gold.query(
            f"SELECT tienda, SUM(ventas_eur) AS ventas FROM {TABLE} "
            "WHERE mes BETWEEN ? AND ? GROUP BY tienda ORDER BY ventas DESC",
            [date(2026, 1, 1), date(2026, 6, 1)], connection=con)

    report = Report.from_manifest(PROJECT, lang="es")                 # 2. página web
    report.add_kpi("Ventas", f"{sum(r[1] for r in rows):,.0f} €")
    report.add_chart(Chart.bar("Ventas por tienda", [r[0] for r in rows], [float(r[1]) for r in rows]))
    report.add_link("Descargar Excel", "ventas.xlsx")
    report.write(output)

    workbook = Workbook.from_manifest(PROJECT)                        # 3. Excel
    workbook.add_sheet("Tiendas", columns, rows, formats={"ventas": "eur"}, source=TABLE)
    workbook.write(output / "ventas.xlsx")
```

El final del fichero (`if __name__ == "__main__": ...`) lo deja la plantilla y no hay que tocarlo.

## 3. Leer de Gold

| Método | Devuelve |
|---|---|
| `gold.query(sql, [parámetros], connection=con)` | `(columnas, filas)`: lista de nombres y lista de tuplas |
| `gold.dataframe(sql, [parámetros], connection=con)` | un `pandas.DataFrame` |

Reglas:

- Abrir **una conexión por informe** (`with gold.connect() as con:`) y pasarla a cada consulta.
- Los valores variables (fechas, códigos) siempre como **parámetros `?`**, nunca pegados en el texto del SQL.
- Solo se puede leer el esquema Gold: cualquier otra tabla da error de permisos.
- Los tipos llegan como tipos Python: `date`/`datetime` para fechas, `Decimal` para
  `decimal`, `int`, `str` y `None` para `NULL`.
- Cada consulta tiene un tiempo máximo (`SQLSERVER_QUERY_TIMEOUT`, 300 s por defecto).

## 4. Página web: `Report`

```python
report = Report.from_manifest(PROJECT, subtitle="01/2026 – 06/2026", kpi_columns=4, lang="es")
```

| Método | Qué añade |
|---|---|
| `add_kpi(etiqueta, valor, detail="", format=None)` | Tarjeta KPI. `format`: `integer`, `number`, `percent` (0,25 → 25 %) o `currency` (USD). Para euros, pasar el texto ya formateado: `f"{valor:,.0f} €"` |
| `add_chart(Chart.bar(título, etiquetas, valores, orientation="v"/"h"))` | Gráfico de barras |
| `add_chart(Chart.line(título, etiquetas, valores))` | Gráfico de líneas |
| `add_chart(Chart.pie(título, etiquetas, valores))` | Gráfico circular |
| `add_chart(Chart(título, trazas, views={"Ventas": trazas1, "Margen": trazas2}))` | Gráfico [Plotly](https://plotly.com/javascript/) libre, con botones para cambiar de vista |
| `add_table(título, columnas, filas, filters=[...], source=TableSource(TABLE, "gold"))` | Tabla. Con `filters` es interactiva: búsqueda, desplegables por columna y orden. `filters=[]` = solo búsqueda y orden |
| `add_link(texto, href)` | Enlace bajo el título, por ejemplo al Excel |
| `add_note(texto)` | Nota al final (periodo, fuente, definiciones) |

Los gráficos ocupan media anchura (`width="half"`) o la anchura completa (`width="full"`).
Las celdas de las tablas se pasan como texto ya formateado.

## 5. Ficheros Excel: `Workbook`

```python
workbook = Workbook.from_manifest(PROJECT, subtitle="01/2026 – 06/2026")
workbook.add_sheet("Tiendas", ["Tienda", "Ventas", "Margen %"], filas,
                   formats={"Ventas": "eur", "Margen %": "percent"}, source=TABLE)
workbook.add_query("Detalle", gold.query(sql, params, connection=con), source=TABLE)
workbook.add_dataframe("Resumen", df)
workbook.add_note("Importes sin IVA.")
workbook.write(output / "ventas-tiendas.xlsx")
```

El fichero tiene:

- una hoja **Info** con título, descripción, periodo, fecha de generación, filas y fuente de cada hoja, y las notas;
- una hoja por cada `add_sheet`/`add_query`/`add_dataframe`, con los datos como **tabla de
  Excel** (filtros, filas alternas), cabecera fija y anchos de columna ajustados.

Formatos (`formats={"columna": "formato"}`):

| Formato | Ejemplo | Formato | Ejemplo |
|---|---|---|---|
| `eur` (o `currency`) | 1.234,50 € | `date` | 31/01/2026 |
| `usd` | $1,234.50 | `datetime` | 31/01/2026 14:30 |
| `percent` | 25,0 % (valor 0,25) | `month` | ene 2026 |
| `integer` | 1.234 | `text` | texto |
| `number` | 1.234,50 | | |

Las columnas sin formato indicado lo toman de sus valores: fechas → `date`, enteros →
`integer`, decimales → `number`. **Pasar valores reales** (números, fechas), no texto
formateado, para que en Excel se puedan sumar y filtrar. Límite de Excel: 1.048.575 filas por hoja.

Las columnas pueden renombrarse en el propio SQL (`SUM(ventas_eur) AS Ventas`); con
`add_query` esos nombres pasan a ser las cabeceras del Excel.

## 6. Generar y publicar

```bash
docker compose run --rm sofibot sofibot build ventas-tiendas    # uno
docker compose run --rm sofibot sofibot build --all             # todos
```

- Si `generate.py` falla, el informe anterior se conserva y el error aparece en la salida del comando.
- El portal muestra el informe en cuanto termina el build.
- Con `SOFIBOT_BUILD_SCHEDULE` el portal regenera todos los informes cada día ([05 · Operación](05-operacion.md)).

## 7. Buenas prácticas

- **Periodos**: usar meses completos (`WHERE mes BETWEEN ? AND ?`) e indicar el periodo en el subtítulo o en una nota.
- **Porcentajes y ratios**: calcularlos desde los totales (margen total / ventas totales), nunca como media de los porcentajes de cada fila.
- **No sumar** totales de dos tablas Gold distintas que describen las mismas ventas.
- **`NULL`** significa "sin datos", no cero: mostrar "Sin datos".
- **No imprimir datos** en `generate.py` (`print`): la salida del build queda en logs.
- Guardar la carpeta `reports/` en un repositorio git para tener historial de cambios.

## 8. Ejemplos

`examples/contoso/reports/` contiene dos informes completos sobre la base pública Contoso:

- `contoso-ventas-tiendas`: KPIs, gráfico mensual con botones de vista, gráfico circular,
  ranking, tabla interactiva con filtro y un Excel de dos hojas.
- `contoso-productos-excel`: solo Excel, tres hojas construidas con `add_query`.

## 9. Crear informes con un asistente de IA

El proyecto incluye instrucciones para asistentes de IA (`AGENTS.md` y la skill
`.claude/skills/nuevo-informe`). El asistente trabaja **solo con `reports/gold_schema.json`**:
escribe el `generate.py` a partir de la estructura, sin ver datos, y una persona lo
construye con `sofibot build` y revisa el resultado. Ver [06 · Seguridad](06-seguridad.md).

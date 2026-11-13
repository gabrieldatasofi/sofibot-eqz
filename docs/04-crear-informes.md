# 04 · Crear informes

Cada informe es una carpeta dentro de `reports/` con dos ficheros:

```
reports/
├── gold_schema.json              estructura de las tablas Gold (sofibot schema)
└── ventas-tiendas/               un proyecto de informe; el nombre de la carpeta es su "slug"
    ├── report.json               nombre, descripción y tablas Gold que lee
    └── generate.py               consultas a Gold y contenido del informe (Python)
```

`report.json`:

```json
{
  "slug": "ventas-tiendas",
  "name": "Ventas por tienda",
  "description": "Ventas y margen de los últimos 12 meses por tienda",
  "tables": ["gold.ventas_mes_tienda"]
}
```

`tables` es obligatorio: lista **todas** las tablas Gold que lee el informe. El build falla
si una consulta lee una tabla Gold que no está en la lista. Con inicio de sesión por Entra
ID, es lo que decide quién ve el informe
([09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md)).

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
- `--table`: la tabla Gold principal del informe. Queda en `tables` de `report.json`. Si
  el informe lee más tablas, añadirlas allí.

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
| `add_table(título, columnas, filas, formats={...}, filters=[...], source=TableSource(TABLE, "gold"))` | Tabla. Con `filters` es interactiva: búsqueda, desplegables por columna y orden. `filters=[]` = solo búsqueda y orden |
| `add_link(texto, href)` | Enlace bajo el título, por ejemplo al Excel |
| `add_note(texto)` | Nota al final (periodo, fuente, definiciones) |

Los gráficos ocupan media anchura (`width="half"`) o la anchura completa (`width="full"`).

Las celdas de las tablas se pasan como **valores reales** (números, fechas, `Decimal`), con
`formats` igual que en `Workbook` (ver la tabla de formatos del apartado 5): la página los
muestra formateados (`1.234,50 €`, `12,5 %`, `ene 2026`) y ordena por el valor real. Las
columnas sin formato lo toman de sus valores. Un texto (por ejemplo `"Sin datos"`) se
muestra tal cual.

```python
report.add_table("Tiendas", ["Tienda", "Ventas", "Margen %"],
                 [[r[0], r[1], r[2] / r[1] if r[1] else "Sin datos"] for r in filas],
                 formats={"Ventas": "eur", "Margen %": "percent"}, filters=["Tienda"])
```

### Botón Excel en cada tabla y gráfico

Cada tabla y cada gráfico lleva un botón **Excel** que descarga ese elemento solo, en un
fichero con una hoja:

- **Tabla interactiva** (con `filters`): las filas que cumplen la búsqueda y los filtros
  aplicados en ese momento (todas, no solo la página visible), en el orden de pantalla.
- **Tabla sin filtros**: todas sus filas.
- **Gráfico**: los datos de la vista que se está viendo (una columna por serie).
- Con **barra de filtros** (apartado siguiente): lo que muestra el gráfico o la tabla con los
  filtros aplicados. Así cada persona se descarga su Excel a medida.

El fichero se genera en el navegador con los datos que ya están en la página; no consulta
la base de datos. Lleva números y fechas reales con su formato, cabecera Datasofi y filtros
de Excel. Por eso solo contiene lo que la página tiene: si la tabla de la página está
recortada (por ejemplo, las 1.000 primeras filas), el botón descarga como mucho esas filas.
Los extractos grandes van en el Excel del informe (`Workbook`).

Para quitar el botón: `add_table(..., download=False)` o `Chart(..., download=False)`.

### Barra de filtros: informes interactivos

Un informe puede llevar una barra de filtros (periodo, país, tienda…) fija arriba de la
página. Al cambiar un filtro se recalculan en el navegador los KPIs, los gráficos y las
tablas que dependen de ella, y sus botones Excel descargan lo filtrado.

```python
from sofibot_eqz import Distinct, Ratio, Report, Sum

rows = gold.query(f"SELECT month, store_name, country, sales_eur, profit_eur FROM {TABLE} "
                  "WHERE month BETWEEN ? AND ?", [primero, ultimo], connection=con)[1]

report.add_dataset("ventas", ["Mes", "Tienda", "País", "Ventas", "Margen"], rows,
                   formats={"Mes": "month", "Ventas": "eur", "Margen": "eur"})
report.add_filter("Periodo", "Mes", kind="range", default=(desde, ultimo))  # desde / hasta
report.add_filter("País", "País")                                            # uno o todos

report.add_dynamic_kpi("Ventas", "ventas", Sum("Ventas"), format="eur")
report.add_dynamic_kpi("Margen %", "ventas", Ratio("Margen", "Ventas"), format="percent")
report.add_dynamic_kpi("Tiendas", "ventas", Distinct("Tienda"), format="integer")

report.add_dynamic_chart("Evolución", "ventas", {"Mes": "Mes", "Año": "Año"},   # botones de granularidad
                         [("Ventas", Sum("Ventas")), ("Margen", Sum("Margen"))], width="full")
report.add_dynamic_chart("Top 10 tiendas", "ventas", "Tienda", [("Ventas", Sum("Ventas"))],
                         kind="hbar", order="desc", top=10)

report.add_dynamic_table("Tiendas", "ventas", ["Tienda", "País"],              # agrupada
                         [("Ventas", Sum("Ventas"), "eur"), ("Margen %", Ratio("Margen", "Ventas"), "percent")])
report.add_dynamic_table("Detalle", "ventas", ["Mes", "Tienda", "Ventas"])     # filas filtradas
```

| Pieza | Qué es |
|---|---|
| `add_dataset(nombre, columnas, filas, formats=...)` | Datos **agregados** que viajan dentro de la página (por ejemplo, mes × tienda) |
| `add_filter(etiqueta, columna, kind="select"/"range", default=...)` | Filtro de la barra. Se aplica a todo lo que lee un dataset con esa columna |
| `Sum(col)`, `Ratio(num, den)`, `Distinct(col)` | Medidas. Un ratio es siempre suma / suma, nunca la media de ratios |
| `add_dynamic_kpi(etiqueta, dataset, medida, format=...)` | KPI. Formatos: `currency` (USD), `eur`, `usd`, `integer`, `number`, `percent`, `change`, `pp` |
| `add_dynamic_chart(título, dataset, x, series, kind="line"/"bar"/"hbar", order="x"/"desc", top=n)` | Gráfico. `x` puede ser `{"Mes": "Mes", "Año": "Año"}` para cambiar de granularidad. `order="desc"` ordena de mayor a menor por la **primera** serie; `"x"` (por defecto) respeta el orden del eje |
| `add_dynamic_table(título, dataset, columnas, medidas=[...])` | Tabla. Con medidas agrupa por `columnas`; sin medidas lista las filas filtradas (extracto a medida) |

Comparación con el periodo anterior: un filtro numérico con `compare=True` (por ejemplo
el año, `add_filter("Año", "Año", default=2026, compare=True)`) y las medidas
`Sum("Ventas").vs_previous()` (variación, formato `change`) o `.previous()`.

**Tamaño**: todas las filas del dataset van dentro de la página. Hay que agregarlas en SQL
(mes × tienda, mes × producto…) y limitar el periodo; decenas de miles de filas van bien,
millones no. El ejemplo `contoso-ventas-tiendas` lleva 36 meses × tiendas.

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
- El portal muestra el informe en cuanto termina el build. Con inicio de sesión por Entra ID,
  solo lo ven las personas con acceso a todas sus tablas (`tables` en `report.json`), según
  `reports/permisos.json` ([09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md)).
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

- `contoso-ventas-tiendas`: informe interactivo con barra de filtros (periodo, país, tienda), KPIs,
  gráficos (con botones de granularidad), tablas que se recalculan y un Excel de dos hojas.
- `contoso-productos-excel`: solo Excel, tres hojas construidas con `add_query`.

Se prueban con su propio entorno, separado del vuestro: ver `examples/contoso/README.md`.

## 9. Crear informes con un asistente de IA

Un asistente de IA puede escribir el `generate.py` por vosotros a partir de
`reports/gold_schema.json`, sin ver datos. Ver [07 · Informes con IA](07-informes-con-ia.md).

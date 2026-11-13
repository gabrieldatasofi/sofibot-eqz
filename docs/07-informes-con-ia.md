# 07 · Crear informes con IA

Un asistente de IA puede escribir los informes por vosotros: le describís lo que queréis
en lenguaje normal y escribe el `generate.py`, con la página web, el Excel o ambos. El
proyecto ya incluye las instrucciones que el asistente necesita.

## Cómo funciona

```
 Vosotros piden el informe ─▶ Asistente lee reports/gold_schema.json (estructura, sin datos)
                                   │
                                   ▼
                          escribe reports/<informe>/generate.py
                                   │
 Vosotros: sofibot build ◀─────────┘   ─▶  revisáis el resultado en el portal  ─▶  cambios
```

El asistente trabaja **solo con la estructura** de las tablas Gold (nombres de columnas,
tipos y descripciones). **No ve los datos**: el informe lo genera una persona con
`sofibot build` y es esa persona quien mira el resultado. Así vuestros datos de negocio no
se envían al proveedor de IA.

Si vuestra política lo permite, podéis decidir otra cosa, pero tened en cuenta que todo lo
que el asistente lee (resultados de consultas, informes, Excel, errores con valores) sale
hacia el servicio de IA.

Este documento describe el asistente trabajando en la carpeta del proyecto. Si el
asistente está en otro equipo y no tiene acceso a la carpeta, puede hacer lo mismo a
través de la API de informes y su servidor MCP: ver [10 · API de esquema e informes](10-api-informes.md).

## Requisitos

| Elemento | Detalle |
|---|---|
| Asistente | **Claude Code** (recomendado: usa la skill incluida). También funcionan Codex, GitHub Copilot u otros que lean `AGENTS.md` |
| Esquema | `reports/gold_schema.json`, generado con `docker compose run --rm sofibot sofibot schema`. Regeneradlo cuando cambien las tablas Gold |
| Descripciones | Cuanto mejor documentadas estén las tablas en SQL Server (grano, moneda, IVA, columnas que no se suman), mejores informes. Ver [03 · Tablas Gold](03-tablas-gold.md) |
| Docker | Para generar los informes, como siempre |

El proyecto incluye:

- `AGENTS.md`: reglas que el asistente lee automáticamente (solo esquema, nunca datos).
- `.claude/skills/nuevo-informe/SKILL.md`: el proceso paso a paso para crear un informe.
- `examples/contoso/reports/`: informes completos que el asistente usa como modelo.

## Paso a paso

1. **Abrir el asistente** en la carpeta del proyecto (con Claude Code: `claude` en una
   terminal dentro de la carpeta, o la extensión de VS Code).

2. **Pedir el informe.** Con Claude Code podéis escribir `/nuevo-informe` seguido de la
   petición, o simplemente pedirlo:

   > Hazme un informe de ventas por tienda de los últimos 12 meses, con un Excel descargable.

3. **Responder sus preguntas.** Si la petición no lo dice, preguntará si queréis un informe
   rápido (formato estándar) o completo, y si lo queréis como página web, Excel o ambos.

4. **El asistente crea el proyecto** (`reports/<informe>/report.json` y `generate.py`) y os
   resume qué muestra y qué tablas lee.

5. **Generarlo:**

   ```bash
   docker compose run --rm sofibot sofibot build <informe>
   ```

6. **Revisarlo** en el portal (`/dashboard`) y abrir el Excel.

7. **Pedir cambios** describiéndolos sin dar valores: *"el gráfico de tiendas, mejor como
   tabla"*, *"añade una hoja con el detalle por producto"*, *"el margen sale en negativo en
   algunas tiendas, revisa el cálculo"*. Volver al paso 5.

## Ejemplos de peticiones

| Petición | Resultado típico |
|---|---|
| *Informe rápido de ventas mensuales* | KPIs del último año, gráfico mensual, tabla de detalle y Excel |
| *Ranking de las 20 tiendas con más margen este año frente al anterior, solo Excel* | Excel con hoja de ranking y hoja de comparación |
| *Informe para dirección: ventas, margen y evolución, sin tablas de detalle* | Página con pocos KPIs y gráficos grandes |
| *Exporta la tabla gold.ventas_mes_producto del último trimestre a Excel* | Excel con los datos filtrados por periodo |
| *Comparativa por familia de producto con filtros por tienda* | Página con gráfico por familia y tabla filtrable |

Consejos:

- Decid **qué decisión** apoya el informe ("qué tiendas revisar") además de qué datos queréis.
- Indicad el **periodo** y la **comparación** (año anterior, mes anterior…).
- Si algo no existe en las tablas Gold (por ejemplo, un dato de clientes que no está), el
  asistente lo dirá y propondrá lo más parecido.

## Cuando un build falla

Copiad al asistente **solo el error**, sin valores de datos. Normalmente basta con las
últimas líneas de la salida de `sofibot build`: el tipo de error de Python y, si es de SQL
Server, su número y mensaje (por ejemplo `Invalid column name 'tienda' (207)`).

| Error frecuente | Qué suele ser |
|---|---|
| `Invalid column name` / `Invalid object name` | Columna o tabla que no está en el esquema: regenerad `gold_schema.json` si las tablas han cambiado |
| `The SELECT permission was denied` | El informe lee algo fuera del esquema Gold |
| `Query timeout expired` | Consulta muy pesada: pedid al asistente que agregue en SQL o filtre por periodo |

Más errores: [Solución de problemas](solucion-de-problemas.md).

## Reglas de seguridad para Claude Code

Además de las instrucciones de `AGENTS.md`, el proyecto incluye `.claude/settings.json`,
que **bloquea técnicamente** en Claude Code lo que el asistente no debe hacer:

- leer la configuración (`.env`), los informes generados (`output/`) y ficheros de datos
  (`.xlsx`, `.csv`, `.parquet`, `.bak`);
- generar o comprobar informes contra la base (`sofibot build`, `sofibot check`, ejecutar
  un `generate.py`), entrar en el contenedor (`docker compose exec`, `docker cp`) o lanzar
  `sqlcmd`.

Sí le deja crear informes (`sofibot new`), editar `generate.py` y `report.json` y comprobar
que compilan. Si intenta algo bloqueado, Claude Code lo impide y os lo indica.

No quitéis reglas de `deny`. Para permisos propios de cada persona, usad
`.claude/settings.local.json` (no se sube a git). Estas reglas son una red de seguridad,
no una garantía completa: `AGENTS.md` sigue aplicando, y para otros asistentes consultad
su documentación sobre permisos.

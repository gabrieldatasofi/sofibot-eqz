# 11 · Funcionalidad 2: consultas de datos

Los usuarios piden **medidas** (ventas, margen…) por **dimensiones** (mes, tienda…) de las
tablas Gold que sus roles permiten, y reciben los datos al momento. Sofibot comprueba sus
permisos, construye la consulta él mismo y registra quién preguntó qué y cómo terminó.

```
 Usuario (rol Sofibot.Consultas)                     servicio "consultas" (contenedor aparte)
   pide: ventas por tienda, ene–mar 2026  ──▶  /api/query ─▶ catálogo ─▶ permisos ─▶ SQL con parámetros ─▶ SQL Server
                                                      │
                                                      └──▶ registro: quién, qué, cómo terminó (sin valores)
```

Es la funcionalidad 2 de Sofibot, separada de la 1 (crear informes, [10 · API de informes](10-api-informes.md)):
comparten solo el inicio de sesión con Entra ID y los permisos por tabla de
`acceso/` (usuarios, roles y permisos). Todo lo demás es propio: contenedor, configuración
(`.env.consultas`), login de SQL Server, registro y esta documentación.

Se pregunta de dos formas, las dos por la misma API y con los mismos permisos:

- **En el portal**, página **Consultas**: un formulario (tabla, medidas, dimensiones,
  periodo, filtro). El portal no consulta la base: reenvía la petición al servicio de
  consultas con el token de Microsoft del propio usuario.
- **Con la IA del usuario** (Claude Code, Claude Desktop o Codex) y el conector MCP de
  consultas: se pregunta en lenguaje normal y la IA consulta a través de Sofibot. **La IA
  recibe los resultados**, que llegan a su proveedor: úsese solo con la cuenta de IA que la
  empresa autorice ([06 · Seguridad](06-seguridad.md)).

## Cómo funciona

- **Catálogo semántico** (`reports/catalogo.json`): qué se puede preguntar a cada tabla.
  La API no acepta SQL: solo nombres del catálogo.
- **Permisos**: el usuario necesita el rol `Sofibot.Consultas` y solo consulta las tablas
  de sus roles en `acceso/permisos.json`. Las demás tablas no existen para él.
- **Límites**: filas por consulta (`SOFIBOT_QUERY_MAX_ROWS`), tiempo por consulta
  (`SQLSERVER_QUERY_TIMEOUT`) y consultas por minuto y usuario (`SOFIBOT_QUERY_PER_MINUTE`).
- **Registro** (`consultas/registro.sqlite`): cada consulta y cada pregunta, con el usuario
  y el resultado. **Nunca los valores devueltos.**

## El catálogo: `reports/catalogo.json`

```json
{
  "tables": {
    "gold.ventas_mes_tienda": {
      "description": "Ventas mensuales por tienda, en euros sin IVA",
      "period": "mes",
      "dimensions": {
        "mes": {"column": "mes", "description": "Mes natural"},
        "tienda": {"column": "tienda", "description": "Nombre de la tienda", "synonyms": ["local"]}
      },
      "measures": {
        "ventas": {"sum": "ventas_eur", "format": "eur", "synonyms": ["facturación"]},
        "margen_pct": {"ratio": ["margen_eur", "ventas_eur"], "format": "percent"},
        "tiendas": {"distinct": "tienda", "format": "integer"}
      },
      "rules": ["No sumar con gold.ventas_mes_producto: describen las mismas ventas"]
    }
  }
}
```

| Campo | Qué es |
|---|---|
| `period` | Columna de fecha de la tabla (meses completos). Sin ella, la tabla no admite periodo |
| `dimensions` | Por qué se puede agrupar o filtrar: nombre (minúsculas, sin espacios) → columna |
| `measures` | Qué se puede calcular: `sum` (suma de una columna), `ratio` (suma / suma, nunca media de porcentajes) o `distinct` (valores distintos). `format`: `eur`, `usd`, `percent`, `integer`, `number`… |
| `description`, `synonyms` | Para que las personas, y más adelante el agente, sepan qué es cada cosa |
| `rules` | Avisos que acompañan a la tabla |

Comprobarlo contra el esquema (sin leer datos):

```bash
docker compose run --rm sofibot sofibot catalog
```

El catálogo es código, como los informes: lo puede proponer un asistente de IA viendo solo
el esquema (funcionalidad 1) y lo revisa una persona. Ejemplo completo:
`examples/contoso/reports/catalogo.json`.

## Instalación

1. **Login de SQL Server propio.** Ejecutar `sql/crear-login-lectura.sql` con
   `@login = N'sofibot_consultas'` (otra contraseña). Es de solo lectura, como el del portal,
   pero separado: se puede revocar o limitar sin tocar los informes.
2. **Rol `Sofibot.Consultas`** en Administración → Usuarios y la API expuesta en Entra ID
   ([09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md#roles-de-las-funcionalidades)).
3. **Configuración propia**: `cp .env.consultas.example .env.consultas` y rellenarlo
   (servidor, login del paso 1, `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`).
4. **El catálogo**: `reports/catalogo.json`, comprobado con `sofibot catalog`.
5. **Activar el contenedor**: en `.env`, `COMPOSE_PROFILES=consultas` (con el proxy HTTPS,
   `COMPOSE_PROFILES=https,consultas`) y `SOFIBOT_QUERY_URL=http://consultas:8080`, para que
   el portal muestre la página **Consultas** y pida a Microsoft el token de la API al iniciar
   sesión. En Linux, `mkdir consultas` con el mismo dueño que `reports/` y `output/`. Después:

   ```bash
   docker compose up -d
   ```

Con el proxy HTTPS, la API queda en `https://<vuestro dominio>/api/query`; sin él, en
`http://localhost:8081` (`SOFIBOT_QUERY_PORT`).

## Rutas

Todas con `Authorization: Bearer <token de Entra ID del usuario>`. Opcional:
`X-Sofibot-Channel: portal | mcp | api` (canal que queda en el registro).

| Método y ruta | Qué hace |
|---|---|
| `GET /api/query/catalog` | Lo que el usuario puede consultar: sus tablas, medidas y dimensiones (sin nombres de columnas) |
| `POST /api/query` | Ejecuta una consulta (abajo) |
| `POST /api/query/outcome` | Registra cómo terminó una pregunta, también cuando no hubo consulta |
| `GET /health` | Comprobación del contenedor |

Consulta:

```json
{
  "table": "gold.ventas_mes_tienda",
  "measures": ["ventas", "margen_pct"],
  "dimensions": ["tienda"],
  "filters": [{"dimension": "tienda", "values": ["Madrid", "Bilbao"]}],
  "period": {"from": "2026-01", "to": "2026-03"},
  "order": {"by": "ventas", "desc": true},
  "limit": 20
}
```

Respuesta: `query_id`, `columns`, `rows`, `truncated` (si había más filas que el límite),
`period` y el formato de cada medida. `null` significa sin datos, no cero.

Desenlace de una pregunta (`POST /api/query/outcome`): `{"outcome": "respondida" |
"no_disponible" | "ambigua" | "rechazada" | "error", "question": "...", "reason": "...",
"query_ids": [...]}`. El texto de la pregunta solo se guarda con
`SOFIBOT_QUERY_STORE_QUESTIONS=1`, y se borra a los `SOFIBOT_QUERY_QUESTION_DAYS` días.

## Con Claude o Codex: el conector MCP de consultas

`mcp-server/sofibot_consultas_mcp.py`, con tres herramientas:

| Herramienta | Qué hace |
|---|---|
| `describe_catalog` | Lo que el usuario puede consultar |
| `run_query` | Una consulta estructurada (tabla, medidas, dimensiones, filtros, periodo, orden, límite) |
| `record_outcome` | Cómo terminó cada pregunta, también las que no se pudieron responder |

Sus instrucciones piden a la IA que use solo el catálogo, pregunte si hay ambigüedad, no
invente cifras, diga qué consultó y registre el desenlace de **cada** pregunta. Cada
persona lo instala desde la página **Conectar tu IA** del portal: descarga
`sofibot-conectar.zip` y hace doble clic en `sofibot-mcp.exe`, que configura Claude
Desktop, Claude Code y Codex (sin Python). También hay configuración manual. El fichero
público `/conexion.json` da al conector la dirección de Sofibot y los identificadores de
Entra ID (ningún secreto). La primera vez se abre
el navegador para iniciar sesión con Microsoft.

## Registro

`consultas/registro.sqlite`, dos tablas:

| Tabla | Una fila por | Columnas |
|---|---|---|
| `consultas` | consulta | fecha, usuario, roles, canal, tabla, medidas, dimensiones, filtros, periodo, filas devueltas, duración, resultado (`correcta`, `rechazada`, `error`) y motivo |
| `preguntas` | pregunta | fecha, usuario, canal, texto (si está permitido), desenlace, motivo, consultas relacionadas |

Los errores de SQL Server se registran solo por su tipo: sus mensajes pueden citar valores.
Exportar para analizarlo (por ejemplo, un informe *¿Qué pregunta la gente?*):

```bash
docker compose run --rm consultas sofibot consultas-registro consultas --out /app/consultas/consultas.csv
docker compose run --rm consultas sofibot consultas-registro preguntas --out /app/consultas/preguntas.csv
```

## Con una cuenta local (sin Microsoft)

Una cuenta local ([09 · Cuentas locales](09-inicio-sesion-entra.md#cuentas-locales-sin-entra-id))
no puede iniciar sesión con Microsoft: su conector usa un **token personal** que genera en
**Conectar tu IA → Generar token personal** (variable `SOFIBOT_API_TOKEN` del conector), firmado
por Sofibot con `SOFIBOT_LOCAL_SECRET`. Tiene los mismos roles y tablas que la cuenta, caduca y
deja de valer al cambiar su contraseña.

## Seguridad

- La API no acepta SQL: los nombres de tablas y columnas salen del catálogo y todos los
  valores van como parámetros.
- La comprobación de permisos está en la API: el usuario (o un agente que actúe por él)
  no puede pedir una tabla que sus roles no permiten.
- Contenedor, configuración y login de SQL Server propios: el portal no conoce sus
  credenciales y este servicio no conoce las del portal.
- Los tokens deben ser de un usuario (delegados): el token de una aplicación no sirve.

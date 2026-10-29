# Sofibot · Informes desde SQL Server

Sofibot se conecta en **solo lectura** a las tablas **Gold** de vuestro warehouse en
Microsoft SQL Server y genera a partir de ellas:

- **Informes web** interactivos: KPIs, gráficos y tablas con búsqueda y filtros.
- **Ficheros Excel** con formato: una hoja por tabla, con filtros y formatos de número y fecha.

Todo se entrega en un **contenedor Docker**. Los informes se publican en un portal web
y se regeneran automáticamente cada día.

```
 SQL Server (esquema gold)  ──solo lectura──▶  Sofibot (Docker)  ──▶  Portal web + Excel
                                                 │
                                   reports/  proyectos de informe (código)
                                   output/   informes generados
```

## Puesta en marcha en 5 pasos

| Paso | Qué hacer | Detalle |
|---|---|---|
| 1 | Instalar Docker y copiar esta carpeta al servidor | [01 · Instalación](docs/01-instalacion.md) |
| 2 | Crear el login de solo lectura en SQL Server con `sql/crear-login-lectura.sql` | [02 · Conexión](docs/02-conexion-sql-server.md) |
| 3 | Copiar `.env.example` a `.env` y rellenar servidor, base de datos y login | [Configuración](docs/configuracion.md) |
| 4 | Comprobar la conexión y obtener el esquema | `docker compose run --rm sofibot sofibot check` y `... sofibot schema` |
| 5 | Crear los informes y arrancar el portal | [04 · Crear informes](docs/04-crear-informes.md) |

```bash
cp .env.example .env                                   # y rellenarlo
docker compose build
docker compose run --rm sofibot sofibot check          # ¿conecta? ¿ve las tablas gold?
docker compose run --rm sofibot sofibot schema         # reports/gold_schema.json
docker compose run --rm sofibot sofibot new ventas-tiendas --name "Ventas por tienda" --table gold.mi_tabla
docker compose run --rm sofibot sofibot build --all
docker compose up -d                                   # portal: http://localhost:8080
```

## Documentación

| Documento | Para quién | Contenido |
|---|---|---|
| [01 · Instalación](docs/01-instalacion.md) | Sistemas | Requisitos, Docker, carpetas, actualización |
| [02 · Conexión a SQL Server](docs/02-conexion-sql-server.md) | DBA / Sistemas | Login de solo lectura, red, cifrado, comprobación |
| [03 · Tablas Gold](docs/03-tablas-gold.md) | Equipo de datos | Qué tablas espera Sofibot, cómo documentarlas, el contrato de esquema |
| [04 · Crear informes](docs/04-crear-informes.md) | Equipo de datos / desarrollo | Proyectos de informe, página web, Excel, ejemplos |
| [05 · Operación](docs/05-operacion.md) | Sistemas | Portal, regeneración diaria, API, logs, copias |
| [06 · Seguridad](docs/06-seguridad.md) | Todos | Qué puede y qué no puede hacer Sofibot |
| [Configuración](docs/configuracion.md) | Sistemas | Todas las variables de `.env` |
| [Solución de problemas](docs/solucion-de-problemas.md) | Todos | Errores frecuentes de conexión y de generación |

## Contenido de esta carpeta

| Ruta | Qué es |
|---|---|
| `compose.yaml`, `Dockerfile` | Contenedor Docker de Sofibot |
| `.env.example` | Plantilla de configuración (copiar a `.env`) |
| `sql/crear-login-lectura.sql` | Script para el DBA: login con SELECT solo sobre el esquema Gold |
| `reports/` | **Vuestros proyectos de informe** (uno por carpeta) y `gold_schema.json` |
| `output/` | Informes generados (HTML y Excel). Se sirven en el portal |
| `docs/` | Documentación |
| `examples/contoso/` | Ejemplo completo sobre la base pública Contoso |
| `src/sofibot_eqz/` | Código de Sofibot (conexión, informes, Excel, portal) |
| `tests/` | Pruebas automáticas |

Soporte: Datasofi.

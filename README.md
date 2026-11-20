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

> **¿Queréis probarlo en un PC con Windows?** Seguid
> [00 · Probar en Windows](docs/00-prueba-en-windows.md): de instalar Docker Desktop a ver
> el primer informe, comando a comando.

| Paso | Qué hacer | Detalle |
|---|---|---|
| 1 | Instalar Docker y descargar Sofibot | PC con Windows: [00 · Probar en Windows](docs/00-prueba-en-windows.md). Servidor: [00 · Instalación en Debian](docs/00-instalacion-debian-paso-a-paso.md) o [01 · Instalación](docs/01-instalacion.md) |
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

- Si el primer `check` falla, el propio mensaje indica qué hacer (certificado, contraseña,
  red…). Más casos en [Solución de problemas](docs/solucion-de-problemas.md).
- Si `docker compose up` responde *port is already allocated*, otro programa usa el puerto
  8080: poned otro en `SOFIBOT_PORT` dentro de `.env` (por ejemplo `8085`).

## Documentación

| Documento | Para quién | Contenido |
|---|---|---|
| [00 · Probar en Windows](docs/00-prueba-en-windows.md) | Quien prueba | **Empezad aquí para probar**: Docker Desktop en un PC con Windows, comando a comando |
| [00 · Instalación paso a paso en Debian](docs/00-instalacion-debian-paso-a-paso.md) | Sistemas | Para el uso diario: de un servidor Debian vacío a Sofibot funcionando, comando a comando |
| [00 · Instalación con ayuda de un asistente de IA](docs/00-instalacion-con-ia.md) | El asistente de IA (Claude Code, Codex) de quien instala | Guion para que el asistente guíe la instalación sin ver contraseñas ni datos. Va en el paquete como `INSTALAR-CON-IA.md`, con `AGENTS.md`, `CLAUDE.md` y `.claude/settings.json` |
| [00 · Instalación con imagen publicada](docs/00-instalacion-con-imagen.md) | Sistemas del cliente / Datasofi | Instalar sin código fuente: `docker compose pull` de la imagen publicada por Datasofi. Incluye cómo publicar una versión y dar acceso de solo lectura |
| [00 · Sofibot completo paso a paso](docs/00-sofibot-completo-paso-a-paso.md) | Sistemas / Administrador de Entra ID | Después de la anterior: HTTPS, Entra ID (con checklist para su administrador), informes con IA, consultas, permisos y conectores de Claude y Codex |
| [01 · Instalación](docs/01-instalacion.md) | Sistemas | Referencia: requisitos, carpetas, versiones, actualización, instalación sin internet |
| [02 · Conexión a SQL Server](docs/02-conexion-sql-server.md) | DBA / Sistemas | Login de solo lectura, red, cifrado, comprobación |
| [03 · Tablas Gold](docs/03-tablas-gold.md) | Equipo de datos | Qué tablas espera Sofibot, cómo documentarlas, el contrato de esquema |
| [04 · Crear informes](docs/04-crear-informes.md) | Equipo de datos / desarrollo | Proyectos de informe, página web, Excel, ejemplos |
| [05 · Operación](docs/05-operacion.md) | Sistemas | Portal, regeneración diaria, API, logs, copias |
| [06 · Seguridad](docs/06-seguridad.md) | Todos | Qué puede y qué no puede hacer Sofibot |
| [07 · Informes con IA](docs/07-informes-con-ia.md) | Equipo de datos | Crear informes pidiéndoselos a un asistente de IA, sin que vea los datos |
| [08 · Acceso desde la red con HTTPS](docs/08-acceso-https.md) | Sistemas | Abrir el portal al resto de la empresa: nombre en el DNS, certificado, proxy HTTPS incluido |
| [09 · Inicio de sesión con Entra ID](docs/09-inicio-sesion-entra.md) | Sistemas | Cada persona entra con su cuenta de la empresa y ve solo los informes de su rol |
| [10 · API de informes](docs/10-api-informes.md) | Sistemas / Equipo de datos | Funcionalidad 1: los asistentes de IA de los autores escriben borradores de informe por API o MCP, sin ver datos; un revisor los previsualiza y publica |
| [11 · Consultas de datos](docs/11-consultas.md) | Sistemas / Equipo de datos | Funcionalidad 2: consultar medidas por dimensiones de las tablas Gold con los permisos de cada persona, con registro de quién preguntó qué |
| [12 · Arquitectura técnica](docs/12-arquitectura.md) | Sistemas / Datasofi | Piezas, pantallas, identidad, las dos funcionalidades, MCP, carpetas y código |
| [Configuración](docs/configuracion.md) | Sistemas | Todas las variables de `.env` y `.env.consultas` |
| [Solución de problemas](docs/solucion-de-problemas.md) | Todos | Errores frecuentes de conexión y de generación |

## Contenido de esta carpeta

| Ruta | Qué es |
|---|---|
| `compose.yaml`, `Dockerfile` | Contenedor Docker de Sofibot |
| `requirements.txt` | Versiones exactas de todas las dependencias de Python |
| `.env.example` | Plantilla de configuración (copiar a `.env`) |
| `sql/crear-login-lectura.sql` | Script para el DBA: login con SELECT solo sobre el esquema Gold |
| `reports/` | **Vuestros proyectos de informe** (uno por carpeta) y `gold_schema.json` |
| `output/` | Informes generados (HTML y Excel). Se sirven en el portal |
| `mcp-server/` | Servidor MCP para conectar un asistente de IA a la API de informes ([10 · API](docs/10-api-informes.md)) |
| `consultas/` | Registro del servicio de consultas ([11 · Consultas](docs/11-consultas.md)). Se crea al activarlo |
| `docs/` | Documentación |
| `examples/contoso/` | Ejemplo completo sobre la base pública Contoso |
| `src/sofibot_eqz/` | Código de Sofibot (conexión, informes, Excel, portal) |
| `tests/` | Pruebas automáticas |

Soporte: Datasofi.

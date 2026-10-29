# Configuración

Toda la configuración está en el fichero `.env` (plantilla: `.env.example`). Tras
cambiarlo: `docker compose up -d` (recrea el contenedor con los nuevos valores).

## SQL Server

| Variable | Por defecto | Descripción |
|---|---|---|
| `SQLSERVER_HOST` | — (obligatoria) | Nombre o IP del servidor. `servidor\INSTANCIA` para una instancia con nombre. `host.docker.internal` = el equipo donde corre Docker |
| `SQLSERVER_PORT` | `1433` | Puerto TCP. Vacío para resolver una instancia con nombre por SQL Browser |
| `SQLSERVER_DATABASE` | — (obligatoria) | Base de datos del warehouse |
| `SQLSERVER_AUTH` | `sql` | `sql`: usuario y contraseña de SQL Server. `entra-sp`: principal de servicio de Entra ID (Azure SQL, Fabric). `windows`: usuario de Windows, solo sin Docker |
| `SQLSERVER_USER` | — | Login (`sql`) o client ID de la aplicación (`entra-sp`) |
| `SQLSERVER_PASSWORD` | — | Contraseña (`sql`) o secret de la aplicación (`entra-sp`) |
| `SQLSERVER_GOLD_SCHEMA` | `gold` | Esquema de las tablas Gold |
| `SQLSERVER_ENCRYPT` | `yes` | `yes`, `strict` (TDS 8.0, SQL Server 2022+) o `no` |
| `SQLSERVER_TRUST_CERTIFICATE` | `0` | `1` acepta cualquier certificado del servidor. Solo para pruebas |
| `SQLSERVER_LOGIN_TIMEOUT` | `15` | Segundos para establecer la conexión |
| `SQLSERVER_QUERY_TIMEOUT` | `300` | Segundos máximos por consulta |
| `SQLSERVER_DRIVER` | `ODBC Driver 18 for SQL Server` | Driver ODBC (el incluido en la imagen) |

## Portal e informes

| Variable | Por defecto | Descripción |
|---|---|---|
| `SOFIBOT_ADMIN_TOKEN` | — | Token de la API de administración. Mínimo 32 caracteres. Sin él, la API responde 503 |
| `SOFIBOT_VIEWER_USER` | `equivalenza` | Usuario para ver el portal |
| `SOFIBOT_VIEWER_PASSWORD` | — | Si tiene valor, el portal pide usuario y contraseña |
| `SOFIBOT_BUILD_SCHEDULE` | — | Horas de regeneración diaria, `HH:MM` separadas por comas |
| `TZ` | `Europe/Madrid` | Zona horaria de las horas programadas y de las fechas de los informes |
| `SOFIBOT_BUILD_TIMEOUT` | `900` | Segundos máximos por informe |

## Docker (`compose.yaml`)

| Variable | Por defecto | Descripción |
|---|---|---|
| `SOFIBOT_BIND` | `127.0.0.1` | Interfaz donde se publica el portal. `0.0.0.0` = todas |
| `SOFIBOT_PORT` | `8080` | Puerto del portal en el servidor |
| `SOFIBOT_UID`, `SOFIBOT_GID` | `10001` | Usuario y grupo con el que se ejecuta el contenedor (dueño de `reports/` y `output/`) |

## Generar valores aleatorios

```bash
openssl rand -base64 36                                              # Linux
docker compose run --rm sofibot python -c "import secrets; print(secrets.token_urlsafe(36))"
```

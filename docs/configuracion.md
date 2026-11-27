# Configuración

Toda la configuración está en el fichero `.env` (plantilla: `.env.example`). En producción
Linux, las contraseñas y tokens van aparte, en `/etc/sofibot/secretos.env` y
`/etc/sofibot/secretos-consultas.env` (solo root), y tienen prioridad sobre `.env` y
`.env.consultas` ([00 · Instalación con imagen](00-instalacion-con-imagen.md#producción-en-linux-secretos-fuera-de-la-carpeta)). Tras
cambiarlo: `docker compose up -d` (recrea el contenedor con los nuevos valores).

Para comprobar qué falta sin mostrar ningún valor: `docker compose run --rm sofibot sofibot config`
(y `docker compose run --rm consultas sofibot config --consultas` para `.env.consultas`).
Dice qué variables están rellenas o faltan y los modos activos (`sql`/`entra`, `on`/`off`,
el esquema Gold), nunca contraseñas, tokens, servidores ni URLs: su salida se puede enseñar
a quien os ayude, también a un asistente de IA.

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
| `SOFIBOT_CODE_API` | `off` | Funcionalidad 1, API de informes para asistentes de IA ([10 · API de informes](10-api-informes.md)): `off`, `entra` o `local` (cada autor con su token, de Microsoft o de una cuenta local, y el rol `Sofibot.Autor`; los dos aceptan ambos) o `token` (token compartido, solo para pruebas) |
| `SOFIBOT_API_TOKEN` | — | Token compartido de la API de informes, solo con `SOFIBOT_CODE_API=token`. Mínimo 32 caracteres, distinto del de administración |
| `SOFIBOT_REVIEW_OWN` | `0` | `1` permite a un revisor publicar un borrador que envió él mismo |
| `SOFIBOT_QUERY_URL` | — | Dirección interna del servicio de consultas, `http://consultas:8080`. Activa la página Consultas del portal |
| `SOFIBOT_QUERY_PUBLIC_URL` | `SOFIBOT_PUBLIC_URL` | Dirección del servicio de consultas para los conectores de Claude y Codex, si no está detrás del mismo proxy HTTPS (por ejemplo, `http://localhost:8086` en pruebas) |
| `SOFIBOT_API_SCOPE` | `api://<ENTRA_CLIENT_ID>/access_as_user` | Ámbito que pide el portal para reenviar consultas |
| `SOFIBOT_DRAFTS_DIR` | `reports/.borradores` | Carpeta de los borradores escritos por la API |
| `SOFIBOT_AUTH` | ver descripción | Inicio de sesión en el portal: `entra`, `local` (solo cuentas locales, sin Entra ID), `basic` o `none` ([05 · Operación](05-operacion.md)). Sin valor: `basic` si hay `SOFIBOT_VIEWER_PASSWORD`, `none` si no |
| `SOFIBOT_LOCAL_SECRET` | — | Firma de los tokens de las cuentas locales (conectores y Consultas). Mínimo 32 caracteres, distinto de los otros tokens; el mismo valor en `.env.consultas` ([09 · Cuentas locales](09-inicio-sesion-entra.md#cuentas-locales-sin-entra-id)) |
| `SOFIBOT_LOCAL_ACCOUNTS` | `password,totp` | Qué cuentas locales pueden entrar: `password` (usuario y contraseña, `acceso/cuentas-locales.json`), `totp` (además, código de una app de autenticación, `acceso/cuentas-totp.json`) o las dos. `totp` recomendado en producción ([09 · Cuentas locales con TOTP](09-inicio-sesion-entra.md#cuentas-locales-con-totp-contraseña-y-código-del-móvil)) |
| `SOFIBOT_LOCAL_ACCOUNTS_WEB` | `0` | `1` permite a los administradores crear cuentas con TOTP con una contraseña temporal (la persona elige su contraseña y escanea su QR al entrar la primera vez), restablecerlas o borrarlas en Administración → Cuentas locales ([09](09-inicio-sesion-entra.md#crear-cuentas-con-totp-desde-el-portal)). Las de solo contraseña, siempre en el servidor |
| `SOFIBOT_LOCAL_ACTIVATION_DAYS` | `7` | Días que vale la contraseña temporal de una cuenta creada desde el portal (1 a 30) |
| `SOFIBOT_LOCAL_TOKEN_DAYS` | `30` | Días que dura el token personal de una cuenta local (1 a 365) |
| `SOFIBOT_VIEWER_USER` | `equivalenza` | Usuario compartido (`basic`) |
| `SOFIBOT_VIEWER_PASSWORD` | — | Contraseña compartida (`basic`) |
| `SOFIBOT_BUILD_SCHEDULE` | — | Horas de regeneración diaria, `HH:MM` separadas por comas |
| `TZ` | `Europe/Madrid` | Zona horaria de las horas programadas y de las fechas de los informes |
| `SOFIBOT_BUILD_TIMEOUT` | `900` | Segundos máximos por informe |

## Inicio de sesión con Microsoft Entra ID

Solo con `SOFIBOT_AUTH=entra`. Ver [09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md).

| Variable | Por defecto | Descripción |
|---|---|---|
| `SOFIBOT_PUBLIC_URL` | — | Dirección del portal, `https://...`, sin `/` final. La URI de redirección registrada en Entra ID es esta más `/auth/callback` |
| `ENTRA_TENANT_ID` | — | Id. de directorio (inquilino) |
| `ENTRA_CLIENT_ID` | — | Id. de aplicación (cliente) |
| `ENTRA_CLIENT_SECRET` | — | Valor del secreto de cliente. Caduca: renovarlo antes de la fecha |
| `SOFIBOT_SESSION_HOURS` | `8` | Horas que dura la sesión antes de volver a pasar por Microsoft |
| `HTTPS_PROXY` | — | Proxy de salida a internet, si lo hay, para llegar a `login.microsoftonline.com` |

Entra ID solo valida el inicio de sesión. Los roles de cada persona están en `acceso/usuarios.json` y
las tablas Gold de cada rol de datos en `acceso/permisos.json` (los dos se editan en Administración;
la carpeta se cambia con `SOFIBOT_ACCESS_DIR`, por defecto `acceso/`).

## Docker (`compose.yaml`)

| Variable | Por defecto | Descripción |
|---|---|---|
| `SOFIBOT_BIND` | `127.0.0.1` | Interfaz donde se publica el portal. `0.0.0.0` = todas |
| `SOFIBOT_PORT` | `8080` | Puerto del portal en el servidor |
| `SOFIBOT_UID`, `SOFIBOT_GID` | `10001` | Usuario y grupo con el que se ejecuta el contenedor (dueño de `reports/`, `output/`, `acceso/` y `consultas/`) |
| `SOFIBOT_QUERY_PORT` | `8081` | Puerto del servicio de consultas en el servidor (perfil `consultas`) |

## Proxy HTTPS

Ver [08 · Acceso desde la red con HTTPS](08-acceso-https.md).

| Variable | Por defecto | Descripción |
|---|---|---|
| `COMPOSE_PROFILES` | — | `https` arranca el proxy HTTPS (puertos 80 y 443) junto con el portal; `consultas`, el servicio de consultas. Los dos: `https,consultas` |
| `SOFIBOT_DOMAIN` | — | Nombre con el que se abre el portal, por ejemplo `informes.empresa.local` |
| `SOFIBOT_TLS` | `internal` | Certificado: `internal` (autoridad propia de Caddy), `"/certs/cert.pem /certs/key.pem"` (certificado corporativo en `caddy/certs/`) o un correo (Let's Encrypt, solo dominios públicos) |

## Servicio de consultas: `.env.consultas`

Funcionalidad 2 ([11 · Consultas](11-consultas.md)). Fichero aparte de `.env`, que solo lee el
contenedor `consultas` (plantilla: `.env.consultas.example`).

| Variable | Por defecto | Descripción |
|---|---|---|
| `SOFIBOT_QUERY_ENABLED` | — | `1` activa el servicio. Sin él responde 503 |
| `SQLSERVER_*` | — | Como en `.env`, pero con un login propio (`sofibot_consultas`) |
| `SQLSERVER_QUERY_TIMEOUT` | `300` | Segundos máximos por consulta. Recomendado: `30` |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` | — | Los mismos que el portal. Sin secreto |
| `SOFIBOT_LOCAL_SECRET` | — | El mismo que el portal, para aceptar los tokens de las cuentas locales |
| `SOFIBOT_QUERY_MAX_ROWS` | `1000` | Filas máximas por consulta |
| `SOFIBOT_QUERY_PER_MINUTE` | `30` | Consultas máximas por usuario y minuto |
| `SOFIBOT_QUERY_STORE_QUESTIONS` | `0` | `1` guarda el texto de las preguntas en el registro |
| `SOFIBOT_QUERY_QUESTION_DAYS` | `90` | Días que se guarda ese texto |

## Generar valores aleatorios

```bash
openssl rand -base64 36                                              # Linux
docker compose run --rm sofibot python -c "import secrets; print(secrets.token_urlsafe(36))"
```

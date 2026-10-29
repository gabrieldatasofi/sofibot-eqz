# Solución de problemas

## Conexión (`sofibot check`)

| Mensaje (extracto) | Causa probable | Solución |
|---|---|---|
| `Missing settings: SQLSERVER_...` | Falta una variable en `.env` | Rellenarla. ¿Existe `.env` (no solo `.env.example`)? |
| `Login timeout expired` / `TCP Provider: Error code 0x2749` / `0x274C` | No hay red hasta el servidor, puerto cerrado o TCP/IP desactivado en SQL Server | Probar `nc -vz servidor 1433`. Revisar firewall, VPN y la configuración de TCP/IP |
| `Named Pipes Provider ... server was not found` | Nombre de servidor incorrecto o instancia con nombre sin SQL Browser | Revisar `SQLSERVER_HOST`; usar el puerto fijo de la instancia |
| `Login failed for user 'sofibot_lectura'` (18456) | Contraseña incorrecta, login inexistente o autenticación de SQL Server desactivada | Re-ejecutar `sql/crear-login-lectura.sql`. Activar "Modo de autenticación de SQL Server y Windows" y reiniciar el servicio |
| `Cannot open database "..." requested by the login` (4060) | El login no tiene usuario en esa base, o el nombre es incorrecto | Revisar `SQLSERVER_DATABASE` y re-ejecutar el script del login |
| `SSL Provider: certificate verify failed` / `The certificate chain was issued by an authority that is not trusted` | El servidor usa un certificado autofirmado o de una CA interna | Instalar un certificado válido en SQL Server. Para pruebas: `SQLSERVER_TRUST_CERTIFICATE=1` |
| `SSL Provider: ... unsupported protocol` / `ssl handshake failure` | SQL Server antiguo (2014 o anterior sin parches de TLS 1.2) | Actualizar SQL Server a una versión con TLS 1.2 |
| `Can't open lib 'ODBC Driver 18 for SQL Server'` | Fuera de Docker: driver no instalado | Instalar el ODBC Driver 18, o usar Docker |
| Aviso `schema 'gold' does not exist` | El esquema tiene otro nombre o el login no puede verlo | `SQLSERVER_GOLD_SCHEMA` y el `GRANT` del script |
| Aviso `the login can write or owns the database` | Se está usando un login administrador | Usar el login de `sql/crear-login-lectura.sql` |

Con `host.docker.internal` y SQL Server en el mismo equipo Windows: comprobar que el
firewall de Windows permite conexiones al puerto 1433 desde la red de Docker.

## Generación de informes (`sofibot build`)

| Mensaje | Causa | Solución |
|---|---|---|
| `Report project not found` | La carpeta no está en `reports/` o le falta `report.json` o `generate.py` | `sofibot list` |
| `slug must be ... equal to the folder name` | El `slug` de `report.json` no coincide con la carpeta | Igualarlos |
| `generate.py failed with exit code 1` | Error en el código del informe | La traza de Python aparece justo encima del mensaje |
| `Invalid object name 'gold.x'` (208) | La tabla no existe o tiene otro nombre | Ver `reports/gold_schema.json` |
| `The SELECT permission was denied` (229) | La consulta lee algo fuera del esquema Gold | Leer solo tablas de Gold |
| `Invalid column name` (207) | La columna ha cambiado de nombre | Regenerar el esquema (`sofibot schema`) y corregir la consulta |
| `Query timeout expired` | Consulta demasiado lenta | Agregar en SQL, filtrar por periodo, pedir una tabla Gold agregada o subir `SQLSERVER_QUERY_TIMEOUT` |
| `exceed Excel's limit` | Más de 1.048.575 filas en una hoja | Filtrar, agregar o repartir en varias hojas |
| `generate.py exceeded 900 s` | El informe completo tarda demasiado | Optimizar las consultas o subir `SOFIBOT_BUILD_TIMEOUT` |
| `Permission denied: '/app/output/...'` | En Linux, `output/` no pertenece al usuario del contenedor | Ver "Permisos de carpetas" en [01 · Instalación](01-instalacion.md) |

## Portal

| Síntoma | Solución |
|---|---|
| `docker compose ps` muestra el contenedor en `Created` y el portal no responde, o `port is already allocated` | Otro programa usa el puerto 8080: cambiar `SOFIBOT_PORT` en `.env` (por ejemplo `8085`) y `docker compose up -d` |
| No abre desde otro equipo | Por defecto solo escucha en `127.0.0.1`: ver "Acceso desde la red" en [05 · Operación](05-operacion.md) |
| `docker compose ps` no muestra `healthy` | `docker compose logs sofibot` |
| Un informe no se actualiza a la hora programada | Revisar `SOFIBOT_BUILD_SCHEDULE` y `TZ`, y los logs a esa hora |
| La API responde 503 `SOFIBOT_ADMIN_TOKEN is not configured` | Definir el token (32+ caracteres) y `docker compose up -d` |

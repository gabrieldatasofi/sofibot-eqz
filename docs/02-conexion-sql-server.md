# 02 · Conexión a SQL Server

Sofibot necesita **un login de SQL Server con permiso SELECT únicamente sobre el esquema
Gold**. Con ese permiso, Sofibot no puede leer otros esquemas ni modificar nada, aunque
alguien cambiara su código.

## 1. Crear el login de solo lectura (DBA)

Abrir `sql/crear-login-lectura.sql` en SSMS, en VS Code con la extensión *SQL Server
(mssql)* o con `sqlcmd`, conectado como administrador. Cambiar los cuatro valores del
principio y ejecutarlo:

```sql
DECLARE @login    sysname       = N'sofibot_lectura';
DECLARE @password nvarchar(128) = N'Una-Contrasena-Larga-2026!';
DECLARE @database sysname       = N'NombreDelWarehouse';
DECLARE @schema   sysname       = N'gold';
```

- **Contraseña sin acentos ni ñ**: larga, con letras, números y símbolos. Los caracteres no
  ingleses pueden guardarse de forma distinta según la herramienta y el login fallaría.
- **Con `sqlcmd`**, añadir `-f 65001` para que lea el fichero como UTF-8:

  ```bash
  sqlcmd -S servidor-sql -E -f 65001 -i sql/crear-login-lectura.sql
  ```

El script:

1. crea (o actualiza) el login de SQL Server `sofibot_lectura` con la política de contraseñas;
2. crea su usuario en la base del warehouse;
3. le concede `SELECT ON SCHEMA::gold`, y nada más.

Las tablas y vistas que se creen después en `gold` quedan accesibles automáticamente.

**Azure SQL Database**: crear un usuario contenido en la base del warehouse (instrucciones
en la cabecera del script). **Microsoft Fabric / Azure con Entra ID**: crear un principal
de servicio (registro de aplicación), darle acceso de lectura al esquema Gold y usar
`SQLSERVER_AUTH=entra-sp` con el *client ID* como usuario y el *secret* como contraseña.

## 2. Red

El servidor donde corre Sofibot debe llegar por TCP al SQL Server:

| Situación | Qué hacer |
|---|---|
| Misma red interna | Abrir el puerto 1433 (o el configurado) del SQL Server para la IP del servidor de Sofibot |
| Sofibot en un VPS / nube y SQL Server en vuestras oficinas | VPN site-to-site o WireGuard entre ambos. **No** publicar el puerto 1433 en internet |
| Azure SQL | Añadir la IP pública del servidor de Sofibot a las reglas de firewall de Azure SQL, o usar un endpoint privado |
| SQL Server en el mismo equipo que Docker | `SQLSERVER_HOST=host.docker.internal` y TCP/IP habilitado en SQL Server Configuration Manager |

Comprobar desde el servidor de Sofibot que el puerto responde:

```bash
nc -vz servidor-sql 1433                                   # Linux
Test-NetConnection servidor-sql -Port 1433                 # Windows PowerShell
```

En SQL Server local, TCP/IP suele venir **desactivado**: SQL Server Configuration Manager →
Configuración de red de SQL Server → Protocolos → TCP/IP → Habilitar, y reiniciar el servicio.
La autenticación de SQL Server (no solo Windows) debe estar activa: propiedades del
servidor → Seguridad → "Modo de autenticación de SQL Server y Windows".

## 3. Configurar `.env`

```ini
SQLSERVER_HOST=servidor-sql.equivalenza.local
SQLSERVER_PORT=1433
SQLSERVER_DATABASE=NombreDelWarehouse
SQLSERVER_AUTH=sql
SQLSERVER_USER=sofibot_lectura
SQLSERVER_PASSWORD=una-contraseña-larga-y-única
SQLSERVER_GOLD_SCHEMA=gold
SQLSERVER_ENCRYPT=yes
SQLSERVER_TRUST_CERTIFICATE=0
```

- **Instancia con nombre** (`SERVIDOR\INSTANCIA`): `SQLSERVER_HOST=servidor\INSTANCIA` y
  `SQLSERVER_PORT=` vacío (requiere el servicio SQL Browser), o mejor, el puerto fijo de
  la instancia en `SQLSERVER_PORT`.
- **Cifrado**: la conexión va cifrada (`SQLSERVER_ENCRYPT=yes`) y comprueba el certificado
  del servidor. Si el SQL Server usa un certificado autofirmado, la opción correcta es
  instalar un certificado válido en el servidor. `SQLSERVER_TRUST_CERTIFICATE=1` evita la
  comprobación: aceptable solo en pruebas o en una red completamente controlada.
- Si la contraseña contiene `#` o espacios, ponerla entre comillas: `SQLSERVER_PASSWORD="ab#c d"`.

Todas las variables: [Configuración](configuracion.md).

## 4. Comprobar

```bash
docker compose run --rm sofibot sofibot check
```

Resultado esperado (no lee ninguna fila, solo metadatos):

```json
{
  "server": "servidor-sql.equivalenza.local,1433",
  "version": "16.0.4135.4",
  "edition": "Enterprise Edition (64-bit)",
  "database": "NombreDelWarehouse",
  "login": "sofibot_lectura",
  "schema": "gold",
  "schema_exists": true,
  "can_read_schema": true,
  "read_only_login": true,
  "tables": [
    {"name": "gold.ventas_mes_tienda", "type": "table"},
    {"name": "gold.ventas_mes_producto", "type": "view"}
  ]
}
Connection OK
```

| Aviso | Significado |
|---|---|
| `schema 'gold' does not exist` | El esquema tiene otro nombre (`SQLSERVER_GOLD_SCHEMA`) o el login no tiene permiso |
| `the login sees no tables` | El esquema existe pero está vacío, o falta `GRANT SELECT ON SCHEMA::gold` |
| `the login can write or owns the database` | Se está usando un login con más permisos de los necesarios. Usar el de `sql/crear-login-lectura.sql` |

Si falla, ver [Solución de problemas](solucion-de-problemas.md).

## 5. Obtener el esquema

```bash
docker compose run --rm sofibot sofibot schema
```

Escribe `reports/gold_schema.json`: tablas, columnas, tipos y descripciones del esquema
Gold, **sin datos**. Es la referencia para escribir informes ([03 · Tablas Gold](03-tablas-gold.md)).
Volver a ejecutarlo cuando cambien las tablas Gold.

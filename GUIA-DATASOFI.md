# Guía Datasofi: de la conexión al informe (prueba con Contoso)

Guía interna para montar y probar Sofibot-EQZ en tu equipo con la base pública Contoso,
antes de entregarlo a Equivalenza. Recorre todo el proceso que hará EQZ, más los pasos
propios de la prueba (restaurar Contoso y crear su capa Gold).

```
 1. SQL Server listo  →  2. Contoso restaurado  →  3. Capa gold  →  4. Login lectura
 →  5. .env  →  6. check / schema  →  7. Informes (HTML + Excel)  →  8. Portal  →  9. Entrega
```

---

## 0. Qué necesitas

| Herramienta | Para qué | Estado en tu equipo (29/10/2026) |
|---|---|---|
| SQL Server 2025 Developer | Base Contoso | Instalado y en marcha. TCP/IP desactivado, solo autenticación Windows y tu usuario sin login |
| `sqlcmd` | Scripts por línea de comandos | Instalado |
| VS Code + extensión **SQL Server (mssql)** o **SSMS 21** | Restaurar el `.bak`, ejecutar los `.sql` | Instalar uno (Azure Data Studio está retirado) |
| Docker Desktop | Ejecutar Sofibot (es el "entorno": lleva Python, el driver ODBC y las librerías dentro) | Instalado. Tiene que estar abierto (icono de la ballena) |
| Python 3.12 | Opcional: ejecutar `sofibot` fuera de Docker | No hace falta |

Con Docker basta para todo el proceso: no instales Python. Un entorno virtual (venv) también necesita un Python instalado para crearse; la imagen Docker ya es ese entorno aislado. Python local solo sirve para iterar algo más rápido con los
informes y para lanzar `pytest`.

---

## 1. Preparar SQL Server (una vez)

En **PowerShell como administrador**:

```powershell
$reg = 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\MSSQL17.MSSQLSERVER\MSSQLServer'
Set-ItemProperty $reg -Name LoginMode -Value 2                          # Windows + SQL Server
Set-ItemProperty "$reg\SuperSocketNetLib\Tcp" -Name Enabled -Value 1    # TCP/IP en 1433

net stop MSSQLSERVER /y
net start MSSQLSERVER /m"SQLCMD"
sqlcmd -S localhost -E -C -Q "IF SUSER_ID(N'$env:USERDOMAIN\$env:USERNAME') IS NULL CREATE LOGIN [$env:USERDOMAIN\$env:USERNAME] FROM WINDOWS; ALTER SERVER ROLE sysadmin ADD MEMBER [$env:USERDOMAIN\$env:USERNAME];"
net stop MSSQLSERVER /y
net start MSSQLSERVER

Test-NetConnection localhost -Port 1433      # TcpTestSucceeded : True
```

- `/m"SQLCMD"` arranca la instancia en modo monousuario, en el que un administrador de
  Windows entra como `sysadmin`. Así te das de alta como administrador de la instancia.
- Si `sqlcmd` dice que la conexión única está ocupada, repite desde el primer `net stop`.

Para que Docker llegue a este SQL Server (paso 8), abre el puerto en el firewall de Windows:

```powershell
New-NetFirewallRule -DisplayName "SQL Server 1433 (Docker)" -Direction Inbound -Protocol TCP -LocalPort 1433 -Action Allow -Profile Private,Domain
```

---

## 2. Restaurar Contoso

Vale cualquiera de las dos versiones de Contoso; el script del paso 3 detecta cuál es:

- **ContosoRetailDW** (Microsoft, 2010, unos 600 MB): *Microsoft Contoso BI Demo Dataset for
  Retail Industry*. Tablas `dbo.FactSales`, `DimStore`, `DimProduct`... Ventas de 2007 a 2009.
- **Contoso V2** (SQLBI): GitHub *Contoso Data Generator V2 Data*, sección *Releases*. Mismo
  modelo que sofibot-project (`Sales`, `Store`, `Product`).

Los comandos usan ContosoRetailDW; con V2 cambia el nombre de la base y del fichero.

1. Copia el `.bak` a la carpeta de backups de la instancia. El servicio de SQL Server no
   puede leer tu carpeta de usuario (`AppData\Local\Temp`, Descargas...):

   ```powershell
   Copy-Item "$env:LOCALAPPDATA\Temp\ContosoRetailDW.bak" "C:\Program Files\Microsoft SQL Server\MSSQL17.MSSQLSERVER\MSSQL\Backup\"
   ```

2. Mira los nombres lógicos de los ficheros del backup:

   ```powershell
   sqlcmd -S localhost -E -C -W -Q "RESTORE FILELISTONLY FROM DISK = N'C:\Program Files\Microsoft SQL Server\MSSQL17.MSSQLSERVER\MSSQL\Backup\ContosoRetailDW.bak'"
   ```

   La primera columna (`LogicalName`) tiene dos filas: la de datos (`Type` = `D`) y la de log (`L`).

3. Restaura con esos dos nombres en lugar de `<datos>` y `<log>`:

   ```powershell
   sqlcmd -S localhost -E -C -Q "RESTORE DATABASE ContosoRetailDW FROM DISK = N'C:\Program Files\Microsoft SQL Server\MSSQL17.MSSQLSERVER\MSSQL\Backup\ContosoRetailDW.bak' WITH MOVE N'<datos>' TO N'C:\Program Files\Microsoft SQL Server\MSSQL17.MSSQLSERVER\MSSQL\DATA\ContosoRetailDW.mdf', MOVE N'<log>' TO N'C:\Program Files\Microsoft SQL Server\MSSQL17.MSSQLSERVER\MSSQL\DATA\ContosoRetailDW_log.ldf', RECOVERY, STATS = 10"
   ```

   Tarda unos minutos y convierte la base de 2010 al formato actual (mensajes
   *Converting database ... from version ...*: es normal). Con SSMS también vale: clic
   derecho en *Databases* → *Restore Database* → *Device* → elegir el `.bak`.

4. Comprueba que están las tablas de origen:

   ```powershell
   sqlcmd -S localhost -E -C -d ContosoRetailDW -W -Q "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES ORDER BY 1, 2"
   ```

   Deben aparecer `dbo.FactSales`, `dbo.DimStore`, `dbo.DimProduct`...

---

## 3. Crear la capa Gold de Contoso

```powershell
sqlcmd -S localhost -E -C -d ContosoRetailDW -i examples\contoso\01-crear-gold.sql
```

Crea `gold.month_store` (mes × tienda, con nombre y país) y `gold.month_product`
(mes × producto, con nombre, marca y categoría), con descripciones `MS_Description`.
Detecta solo si la base es ContosoRetailDW o Contoso V2.

Si falla con `Invalid column name`, tu versión de Contoso tiene otro nombre de columna:
mira las columnas con `SELECT name FROM sys.columns WHERE object_id = OBJECT_ID('dbo.DimStore')`
y ajusta el script.

Esto simula lo que EQZ ya tiene: un esquema `gold` en su warehouse.

---

## 4. Crear el login de solo lectura

Edita los valores del principio de `sql/crear-login-lectura.sql`:

```sql
DECLARE @login    sysname       = N'sofibot_lectura';
DECLARE @password nvarchar(128) = N'<inventa una contraseña larga>';
DECLARE @database sysname       = N'ContosoRetailDW';
DECLARE @schema   sysname       = N'gold';
```

y ejecútalo: `sqlcmd -S localhost -E -C -i sql\crear-login-lectura.sql`.

**No guardes la contraseña en el script** después de ejecutarlo (deja el valor
`CAMBIAR-...` original): el script se entrega a EQZ.

Es exactamente el script que ejecutará el DBA de EQZ.

---

## 5. Configurar `.env`

```powershell
copy .env.example .env
```

Para la prueba con Contoso en tu equipo:

```ini
SQLSERVER_HOST=host.docker.internal
SQLSERVER_PORT=1433
SQLSERVER_DATABASE=ContosoRetailDW
SQLSERVER_AUTH=sql
SQLSERVER_USER=sofibot_lectura
SQLSERVER_PASSWORD=<la del paso 4>
SQLSERVER_GOLD_SCHEMA=gold
SQLSERVER_ENCRYPT=yes
SQLSERVER_TRUST_CERTIFICATE=1
SOFIBOT_ADMIN_TOKEN=<token aleatorio de 32+ caracteres>
SOFIBOT_BUILD_SCHEDULE=
```

- `SQLSERVER_HOST`: `host.docker.internal` con Docker; `localhost` si ejecutas `sofibot` con Python.
- `SQLSERVER_TRUST_CERTIFICATE=1` porque el SQL Server local usa un certificado
  autofirmado. Solo para esta prueba: con EQZ debe ser `0`.
- Token: `python -c "import secrets; print(secrets.token_urlsafe(36))"`.
- No pongas comentarios en la misma línea que un valor: escríbelos en su propia línea.

---

## 6. Comprobar la conexión y obtener el esquema

Con Docker (como lo hará EQZ):

```powershell
docker compose build
docker compose run --rm sofibot sofibot check
docker compose run --rm sofibot sofibot schema
```

O sin Docker, con Python:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest                       # pruebas sin base de datos
sofibot check
sofibot schema
```

`check` debe terminar en `Connection OK`, con `"read_only_login": true` y las dos tablas
`gold.month_store` y `gold.month_product`. `schema` escribe `reports/gold_schema.json`.

Si algo falla: [docs/solucion-de-problemas.md](docs/solucion-de-problemas.md).

---

## 7. Crear informes

Hay tres formas, de más rápida a más elaborada.

### 7.1 Los ejemplos de Contoso

```powershell
Copy-Item -Recurse examples\contoso\reports\* reports\
sofibot build --all          # o: docker compose run --rm sofibot sofibot build --all
```

Genera en `output/`:

- `contoso-ventas-tiendas/`: página con KPIs, gráfico mensual con botones (ventas, margen,
  margen %), ventas por país, top 10 tiendas, tabla filtrable y un Excel de dos hojas.
- `contoso-productos-excel/`: solo un Excel con tres hojas (categorías, ranking, detalle).

### 7.2 Un informe nuevo desde la plantilla

```powershell
sofibot new contoso-categorias --name "Contoso · Categorías" --table gold.month_product
sofibot build contoso-categorias
```

La plantilla funciona sin cambios (exporta la tabla a una página filtrable y a Excel).
Después se edita `reports/contoso-categorias/generate.py`. La API de `Report` (página) y
`Workbook` (Excel) está en [docs/04-crear-informes.md](docs/04-crear-informes.md).

### 7.3 Con IA, como en sofibot-project

Igual que el flujo `nuevo-informe` de sofibot-project, pero adaptado a SQL Server:

1. Abre Claude Code (o Codex) en esta carpeta y pide el informe, por ejemplo:
   *"Crea un informe de las 20 marcas con más margen en el último año, con Excel"*.
2. El asistente usa la skill `.claude/skills/nuevo-informe`: lee **solo**
   `reports/gold_schema.json`, te pregunta si lo quieres rápido o completo y si quieres
   página, Excel o ambos, crea el proyecto con `sofibot new` y escribe `generate.py`.
3. **Tú** lanzas `sofibot build <slug>` y revisas el resultado en el portal.
4. Si falla, pásale la traza del error (sin valores de datos) para que lo corrija.

Diferencias con sofibot-project:

| sofibot-project | sofibot-eqz |
|---|---|
| Esquema por MCP `describe_schema` | Fichero `reports/gold_schema.json` (`sofibot schema`) |
| `report_project.py check` con un warehouse sintético | `sofibot build` contra Contoso (datos públicos) o contra los datos reales, lanzado por una persona |
| `submit` y aprobación en el portal | La persona que lanza el build revisa y publica |
| DuckDB | SQL Server por ODBC |
| Solo HTML | HTML y/o Excel |

Con Contoso, la IA podría ver los datos sin problema porque son públicos, pero mantenemos
la misma disciplina que con EQZ (solo esquema) para que el flujo que entregamos sea el que
hemos probado.

Recomendado: añadir en `.claude/settings.json` reglas `deny` para `Read(.env)`,
`Read(output/**)`, `Read(**/*.xlsx)` y `Bash(sofibot build:*)`, como en sofibot-project.

---

## 8. Probar el portal

```powershell
docker compose up -d --build
```

- `http://localhost:8085/dashboard` (en tu equipo el 8080 lo usa el report-server de sofibot-project, por eso `.env` tiene `SOFIBOT_PORT=8085`): tarjetas de informe con *Ver informe* y descarga de Excel.
- Regenerar por API:

  ```powershell
  curl.exe -X POST http://localhost:8085/api/admin/build-all -H "Authorization: Bearer <SOFIBOT_ADMIN_TOKEN>"
  ```

- Probar la contraseña del portal: `SOFIBOT_VIEWER_PASSWORD=algo` en `.env` y `docker compose up -d`.
- Probar la regeneración programada: `SOFIBOT_BUILD_SCHEDULE=` con la hora de dentro de
  2 minutos, `docker compose up -d` y `docker compose logs -f sofibot`.

Sin Docker: `sofibot serve` (abre en `http://127.0.0.1:8080`).

---

## 9. Checklist antes de entregar a EQZ

- [ ] `pytest` pasa.
- [ ] `docker compose build` funciona desde cero y el contenedor llega a `healthy`.
- [ ] `check`, `schema`, `new`, `build --all` y el portal probados con Contoso por Docker.
- [ ] `sql/crear-login-lectura.sql` con los valores `CAMBIAR-...` originales (sin tu contraseña).
- [ ] `reports/` vacío (solo `.gitkeep`): los ejemplos quedan en `examples/contoso`.
- [ ] `output/` vacío, sin `.env`, sin `.venv`.
- [ ] Decidir si se entrega esta guía (es interna; no contiene secretos).
- [ ] Si EQZ no tiene internet en el servidor: `docker save` de la imagen (ver docs/01-instalacion.md).
- [ ] Pedir a EQZ antes de la instalación: nombre del servidor y base, esquema Gold, cómo
      llega la red (VPN, misma red, Azure), y quién ejecuta el script del login.

Entregar como zip del repositorio (sin `.git` si no quieres darles el historial):

```powershell
git archive --format=zip -o sofibot-eqz-0.1.0.zip HEAD
```

---

## Mapa del código

| Fichero | Qué hace |
|---|---|
| `src/sofibot_eqz/db.py` | `Settings` (lee `SQLSERVER_*`) y `Gold` (conexión pyodbc de solo lectura, `query`, `dataframe`, `server_info`) |
| `src/sofibot_eqz/schema.py` | Contrato de esquema desde el catálogo de SQL Server |
| `src/sofibot_eqz/html.py` | `Report`, `Chart`, `TableSource`: copia de `sofibot_reports` de sofibot-project |
| `src/sofibot_eqz/excel.py` | `Workbook`: Excel con hoja Info y tablas formateadas |
| `src/sofibot_eqz/projects.py` | Crear, listar y construir proyectos de `reports/` en `output/` |
| `src/sofibot_eqz/cli.py` | Comando `sofibot` |
| `src/sofibot_eqz/server.py` | Portal FastAPI, API de administración, regeneración programada |
| `src/sofibot_eqz/template/` | Plantilla de `sofibot new` |

Pendiente para siguientes versiones: inicio de sesión con Entra ID (como sofibot-project),
grupos de informes y permisos por usuario, flujo de envío y aprobación de informes.

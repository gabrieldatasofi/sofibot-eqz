# 01 · Instalación

> **¿Servidor Debian recién instalado?** Seguid [00 · Instalación paso a paso en Debian](00-instalacion-debian-paso-a-paso.md):
> instala Docker y Sofibot comando a comando. Este documento es la referencia completa.

## Requisitos

| Elemento | Requisito |
|---|---|
| Servidor | Linux (recomendado: Ubuntu 22.04/24.04 o Debian 12) o Windows con Docker Desktop. 2 vCPU, 4 GB de RAM y 10 GB de disco son suficientes para empezar |
| Software | Docker Engine 24+ con el plugin Compose (`docker compose version`) |
| Red | Acceso TCP desde el servidor al SQL Server (puerto 1433 por defecto). Ver [02 · Conexión](02-conexion-sql-server.md) |
| SQL Server | SQL Server 2016 o superior, Azure SQL Database, Azure SQL Managed Instance o Microsoft Fabric / Synapse (endpoint SQL) |
| Internet (solo al construir la imagen) | Acceso a `pypi.org`, `packages.microsoft.com` y Docker Hub. Si el servidor no tiene salida a internet, ver "Instalación sin internet" |

No hace falta instalar Python, el driver ODBC ni ninguna herramienta de SQL Server en el
servidor: todo va dentro de la imagen Docker. El driver incluido es **ODBC Driver 18 for
SQL Server**.

## Instalación

1. Copiar esta carpeta al servidor, por ejemplo en `/opt/sofibot`.
2. Crear la configuración:

   ```bash
   cd /opt/sofibot
   cp .env.example .env
   chmod 600 .env            # contiene la contraseña del login de SQL Server
   ```

   Rellenar `.env` siguiendo [02 · Conexión](02-conexion-sql-server.md) y [Configuración](configuracion.md).

3. Construir la imagen:

   ```bash
   docker compose build
   ```

4. Permisos de carpetas (solo Linux). El contenedor no se ejecuta como root, sino como el
   usuario `10001`. Dos opciones:

   ```bash
   sudo chown -R 10001:10001 reports output
   ```

   o bien ejecutarlo con vuestro usuario, añadiendo a `.env`:

   ```
   SOFIBOT_UID=1000      # resultado de: id -u
   SOFIBOT_GID=1000      # resultado de: id -g
   ```

5. Comprobar la conexión: `docker compose run --rm sofibot sofibot check`. Ver [02 · Conexión](02-conexion-sql-server.md).

6. Arrancar el portal:

   ```bash
   docker compose up -d
   docker compose ps        # STATUS debe pasar a "healthy"
   ```

   El portal queda en `http://localhost:8080`. Para abrirlo desde otros equipos, ver
   "Acceso desde la red" en [05 · Operación](05-operacion.md).

## Cómo se ejecutan los comandos

Todos los comandos de Sofibot se lanzan dentro del contenedor:

```bash
docker compose run --rm sofibot sofibot <comando>      # contenedor temporal
docker compose exec sofibot sofibot <comando>          # dentro del portal ya arrancado
```

| Comando | Qué hace |
|---|---|
| `sofibot check` | Prueba la conexión con SQL Server sin leer filas |
| `sofibot schema` | Escribe `reports/gold_schema.json` con la estructura de las tablas Gold |
| `sofibot new <slug> --name "..." --table gold.<tabla>` | Crea un proyecto de informe |
| `sofibot list` | Lista los proyectos de informe |
| `sofibot build <slug>` / `sofibot build --all` | Genera informes en `output/` |
| `sofibot serve` | Arranca el portal (lo hace `docker compose up`) |

## Carpetas

| Carpeta del host | En el contenedor | Contenido | Copia de seguridad |
|---|---|---|---|
| `reports/` | `/app/reports` | Proyectos de informe (código) y `gold_schema.json` | **Sí**: es vuestro trabajo. Mejor aún, en un repositorio git |
| `output/` | `/app/output` | Informes generados | No es necesario: se regeneran con `sofibot build --all` |
| `.env` | variables de entorno | Configuración y contraseñas | Sí, en un lugar seguro |

## Actualizar a una nueva versión

1. Sustituir la carpeta por la nueva versión **conservando** `.env` y `reports/`.
2. `docker compose build && docker compose up -d`.
3. `docker compose exec sofibot sofibot build --all` para regenerar los informes.

## Versiones de las dependencias

Todas las versiones están fijadas, así que construir la imagen hoy o dentro de un año da el
mismo resultado:

| Qué | Dónde se fija | Versión probada |
|---|---|---|
| Python | `Dockerfile` (imagen base) | 3.12.16 sobre Debian 12 |
| ODBC Driver 18 for SQL Server | `Dockerfile` (`MSODBCSQL_VERSION`) | 18.7.1.1 |
| Paquetes de Python, directos e indirectos | `requirements.txt` | Ver el fichero |
| Herramientas de test | `requirements-dev.txt` | pytest 9.2.0 |

Los paquetes de sistema de Debian (`unixodbc`, `tzdata`, certificados) no se fijan: así cada
build incluye los parches de seguridad de Debian 12.

Para actualizar una versión (lo hace Datasofi en cada entrega):

1. Cambiar el rango en `pyproject.toml` si hace falta.
2. En un entorno limpio con Python 3.12: `pip install .` y `pip freeze --exclude sofibot-eqz`.
3. Copiar el resultado a `requirements.txt`, reconstruir la imagen (`docker compose build`),
   pasar los tests y comprobar `sofibot check` y `sofibot build --all`.

## Instalación sin internet

Si el servidor no tiene salida a internet, Datasofi puede entregar la imagen ya
construida como fichero:

```bash
# En un equipo con internet (Datasofi)
docker compose build
docker save datasofi/sofibot-eqz:0.1.0 -o sofibot-eqz-0.1.0.tar

# En el servidor
docker load -i sofibot-eqz-0.1.0.tar
docker compose up -d --no-build
```

## Desarrollo sin Docker (opcional)

Para escribir y probar informes en un equipo Windows sin Docker:

1. Instalar Python 3.12 y el [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).
2. En la carpeta del proyecto:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements-dev.txt
   pip install --no-deps -e .
   sofibot check
   ```

`sofibot` lee `.env` de la carpeta desde la que se ejecuta. En este modo, `SQLSERVER_HOST`
es el nombre real del servidor (no `host.docker.internal`), y se puede usar
`SQLSERVER_AUTH=windows` para entrar con el usuario de Windows.

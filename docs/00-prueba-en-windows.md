# 00 · Probar Sofibot en un PC con Windows

Guía para probar Sofibot en un **PC con Windows 10 u 11** usando Docker Desktop, conectado a
vuestro SQL Server. Cada paso tiene los comandos para copiar y pegar, lo que deberías ver si
ha ido bien y qué hacer si no.

Tiempo aproximado: 30-45 minutos (la instalación de Docker Desktop puede pedir reiniciar).

> Los comandos se escriben en **PowerShell**: menú Inicio → escribe `PowerShell` → *Windows
> PowerShell*. Lo que va entre `< >` lo sustituyes tú (sin los `< >`). Lo que va detrás de
> `#` es un comentario.

> Para el uso diario recomendamos un servidor Linux ([guía Debian](00-instalacion-debian-paso-a-paso.md)):
> en un PC, Sofibot solo funciona mientras el PC está encendido y con la sesión iniciada.
> Lo que hagáis en esta prueba (configuración e informes) se lleva después tal cual.

---

## Antes de empezar: qué necesitas

| Qué | Para qué | Quién te lo da |
|---|---|---|
| Un PC con Windows 10 (22H2) u 11, 8 GB de RAM o más | Donde se prueba Sofibot | Tú / sistemas |
| Permisos de administrador en ese PC (solo para instalar) | Instalar Docker Desktop | Sistemas |
| Que el PC llegue al SQL Server por la red (por ejemplo, estando en la oficina o con VPN) | Conectar | Sistemas / redes |
| Nombre del SQL Server, puerto, base de datos y esquema Gold | Conectar | DBA |
| El login de solo lectura creado con `sql/crear-login-lectura.sql` | Conectar | DBA (paso 5) |

> **Licencia de Docker Desktop**: es gratuito para empresas de menos de 250 empleados y
> menos de 10 millones de dólares de facturación; por encima, Docker exige una suscripción
> de pago. Consultadlo con vuestro departamento de sistemas.

---

## Paso 1 · Instalar Docker Desktop

Abre PowerShell **como administrador** (clic derecho en *Windows PowerShell* → *Ejecutar como
administrador*) y ejecuta:

```powershell
winget install -e --id Docker.DockerDesktop
```

(Alternativa sin `winget`: descargar el instalador desde https://www.docker.com/products/docker-desktop/ y ejecutarlo.)

Cuando termine, **reinicia el PC** si lo pide. Después abre **Docker Desktop** desde el menú
Inicio, acepta las condiciones y espera a que abajo a la izquierda ponga **Engine running**
(la primera vez tarda un par de minutos). No hace falta crear una cuenta de Docker: puedes
saltar ese paso.

Comprueba en una ventana de PowerShell normal:

```powershell
docker run --rm hello-world
docker compose version
```

✅ **Bien si** el primero muestra `Hello from Docker!` y el segundo `Docker Compose version ...`.

❌ **Si no**:
- `docker : The term 'docker' is not recognized` → cierra y vuelve a abrir PowerShell (o reinicia).
- `error during connect ... dockerDesktopLinuxEngine` → Docker Desktop no está abierto o no
  ha terminado de arrancar: ábrelo y espera a *Engine running*.
- Docker Desktop pide **WSL** o dice que la **virtualización** está desactivada → en
  PowerShell como administrador: `wsl --install`, reinicia y vuelve a abrir Docker Desktop.
  Si sigue fallando, hay que activar la virtualización en la BIOS del PC (sistemas).

> Docker Desktop tiene que estar **abierto** cada vez que uséis Sofibot. Para que arranque
> solo: Docker Desktop → *Settings* → *General* → *Start Docker Desktop when you sign in*.

---

## Paso 2 · Descargar Sofibot

**Opción A, con Git** (si está instalado: `git --version` responde algo):

```powershell
cd $HOME
git clone https://github.com/gabrieldatasofi/sofibot-eqz.git sofibot
cd sofibot
```

**Opción B, sin Git:** abre https://github.com/gabrieldatasofi/sofibot-eqz, pulsa el botón
verde **Code** → **Download ZIP**, descomprímelo en tu carpeta de usuario y renombra la
carpeta a `sofibot`. Después, en PowerShell:

```powershell
cd $HOME\sofibot
```

✅ **Bien si** `dir` muestra `README.md`, `compose.yaml`, `docs`, `sql`, `src`…

Desde aquí, todos los comandos se ejecutan **dentro de esta carpeta** (`cd $HOME\sofibot`).

---

## Paso 3 · Comprobar que el PC llega al SQL Server

```powershell
Test-NetConnection <servidor-sql> -Port 1433
```

(Cambia `1433` si vuestro SQL Server usa otro puerto.)

✅ **Bien si** al final pone `TcpTestSucceeded : True`.

❌ **Si no**:
- `TcpTestSucceeded : False` → un firewall, la falta de VPN o que SQL Server no tenga TCP/IP
  activado impiden la conexión. Consulta con sistemas o con el DBA.
- `Name resolution of <servidor-sql> failed` → prueba con la IP del servidor.

**No sigas hasta que este paso funcione**: sin él, Sofibot no puede conectar.

---

## Paso 4 · (Si el SQL Server está en este mismo PC)

Solo si estás probando con un SQL Server instalado en el propio PC: en el paso 6 usarás
`SQLSERVER_HOST=host.docker.internal`, y SQL Server debe tener **TCP/IP activado** y la
**autenticación de SQL Server** permitida. Ver [02 · Conexión](02-conexion-sql-server.md),
apartado 2. Si el SQL Server está en otra máquina, salta este paso.

---

## Paso 5 · Login de solo lectura (lo hace el DBA)

El DBA ejecuta `sql/crear-login-lectura.sql` en el SQL Server (está en la carpeta `sql` que
acabas de descargar). Instrucciones en [02 · Conexión](02-conexion-sql-server.md), apartado 1.

Te tiene que pasar: **usuario**, **contraseña**, **nombre de la base de datos** y **esquema
Gold** (normalmente `gold`).

---

## Paso 6 · Configurar Sofibot (`.env`)

```powershell
copy .env.example .env
$b = New-Object byte[] 36; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b)
notepad .env
```

El segundo comando muestra un texto aleatorio: cópialo, será el token de administración. El
tercero abre el fichero en el Bloc de notas. Cambia estas líneas:

| Línea | Qué poner |
|---|---|
| `SQLSERVER_HOST=` | Nombre o IP del SQL Server (el mismo del paso 3). **Borra** `host.docker.internal`, salvo que el SQL Server esté en este PC (paso 4) |
| `SQLSERVER_PORT=` | Puerto (normalmente `1433`) |
| `SQLSERVER_DATABASE=` | Base de datos (paso 5) |
| `SQLSERVER_USER=` | Usuario (paso 5) |
| `SQLSERVER_PASSWORD=` | Contraseña (paso 5) |
| `SQLSERVER_GOLD_SCHEMA=` | Esquema Gold (paso 5) |
| `SOFIBOT_ADMIN_TOKEN=` | El texto aleatorio que acabas de copiar |

Guarda con **Ctrl+S** y cierra el Bloc de notas.

> No pongas comentarios al final de una línea con valor. Si la contraseña tiene `#` o
> espacios, ponla entre comillas: `SQLSERVER_PASSWORD="ab#c d"`.

---

## Paso 7 · Construir Sofibot y probar la conexión

```powershell
docker compose build
docker compose run --rm sofibot sofibot check
```

La construcción tarda unos minutos la primera vez.

✅ **Bien si** termina con `Connection OK` y en `"tables"` aparecen vuestras tablas Gold.

❌ **Si no**: el mensaje de error incluye un apartado **QUÉ HACER**. Los casos habituales:

| Mensaje | Qué hacer |
|---|---|
| `certificate verify failed` | El certificado del SQL Server no es de confianza (habitual en servidores internos). Para esta prueba, en una red interna: `SQLSERVER_TRUST_CERTIFICATE=1` en `.env` |
| `Login failed` | Usuario o contraseña incorrectos en `.env`, o falta el paso 5 |
| `Login timeout expired` | Vuelve al paso 3 |
| `WARNING: ... sees no tables` | El esquema está vacío o falta el permiso: revisa el paso 5 con el DBA |

> PowerShell puede mostrar en rojo líneas como `Container ... Creating` o `NativeCommandError`:
> son mensajes informativos de Docker, no errores. Lo que cuenta es el final de la salida.

Más casos: [Solución de problemas](solucion-de-problemas.md).

---

## Paso 8 · Esquema y primer informe

```powershell
docker compose run --rm sofibot sofibot schema
docker compose run --rm sofibot sofibot new prueba --name "Prueba" --table <esquema>.<una-tabla-gold>
docker compose run --rm sofibot sofibot build prueba
```

Para `--table` usa una de las tablas que mostró el paso 7, por ejemplo `gold.ventas_mes_tienda`.

✅ **Bien si** el último comando termina con `Built /app/output/prueba`.

---

## Paso 9 · Abrir el portal

```powershell
docker compose up -d
```

Espera unos segundos y abre en el navegador: **http://localhost:8080**

✅ **Bien si** ves "Sofibot · Informes" con la tarjeta del informe *Prueba*, y puedes abrirlo y
descargar su Excel.

❌ **Si no**: `port is already allocated` → otro programa usa el puerto 8080. Cambia
`SOFIBOT_PORT=8080` por otro (por ejemplo `8085`) en `.env`, repite `docker compose up -d` y
abre `http://localhost:8085`.

Los informes generados también están como ficheros en la carpeta `output\` (doble clic en
`index.html` o en el `.xlsx`).

---

## Paso 10 · Crear vuestros informes

Con todo funcionando, ya podéis crear informes sobre vuestras tablas:

- a mano: [04 · Crear informes](04-crear-informes.md);
- con un asistente de IA (sin que vea los datos): [07 · Informes con IA](07-informes-con-ia.md).

Cada informe se genera con `docker compose run --rm sofibot sofibot build <nombre>` y aparece
en el portal.

---

## Al terminar la prueba

| Quiero… | Comando |
|---|---|
| Parar el portal | `docker compose down` |
| Volver a arrancarlo | Abrir Docker Desktop y `docker compose up -d` |
| Actualizar a una versión nueva (con Git) | `git pull`, `docker compose build`, `docker compose up -d` |
| Llevarlo a un servidor | Seguir la [guía Debian](00-instalacion-debian-paso-a-paso.md) y copiar vuestro `.env` y la carpeta `reports\` |
| Desinstalar | `docker compose down --rmi all`, borrar la carpeta `sofibot` y desinstalar Docker Desktop |

# 00 · Instalación con ayuda de un asistente de IA

**Este documento es para el asistente de IA** (Claude Code, Codex u otro) que ayuda a una
persona a instalar Sofibot desde el paquete de Datasofi. Si eres esa persona: abre la carpeta
del paquete con tu asistente y dile *"ayúdame a instalar Sofibot siguiendo INSTALAR-CON-IA.md"*.
Él te guiará; tú ejecutarás los pasos que tocan contraseñas o la base de datos.

La guía para personas, con los mismos pasos, es [INSTALAR.md](00-instalacion-con-imagen.md).

---

## Para el asistente: tu papel

Guías a la persona paso a paso: explicas qué hace cada paso, le das el comando, compruebas
el resultado con el **✅ Bien si** de cada paso antes de seguir y, si algo falla, interpretas
el mensaje de error que ella te enseñe. Hablas en el idioma de la persona y vas de uno en uno:
no le des todos los pasos de golpe.

### Reglas que no se negocian

Esta carpeta es la instalación de Sofibot de una empresa: **contiene las contraseñas de su
SQL Server y da acceso a sus datos**. Sofibot está diseñado para que ningún asistente de IA
vea esos datos ni esas credenciales fuera de los conectores aprobados.

1. **Nunca leas, muestres, edites ni busques dentro de** `.env`, `.env.consultas`, `/etc/sofibot/`, `output/`,
   `consultas/`, `acceso/`, `reports/.admin/`, `caddy/certs/` ni ficheros `.xlsx`, `.csv`, `.sqlite` o
   `.bak`. Tampoco con otro comando (`cat`, `type`, `Get-Content`, `Select-String`, `grep`,
   `findstr`, `more`, scripts…). `.env.example` y `.env.consultas.example` sí puedes leerlos:
   son plantillas sin valores.
2. **Nunca ejecutes nada contra la base de datos**: ni `sqlcmd`, ni SQL, ni Python, ni
   `sofibot check`, `sofibot schema`, `sofibot build`, ni `docker compose run`, `docker run`,
   `docker exec`, `docker compose exec` o `docker cp`. Tampoco comandos que muestran la
   configuración con sus valores: `docker compose config`, `docker inspect`, `docker compose logs`,
   `docker logs`, `env`, `printenv`.
3. **Nunca pidas ni aceptes** contraseñas, tokens ni secretos. Si la persona los pega en la
   conversación, dile que no hacía falta, que no los vas a usar y que, si es un token o una
   contraseña real, lo cambie.
4. **No hagas `docker login`**: lo hace la persona, porque pide el token.
5. **Si te piden consultar datos** ("¿cuánto vendimos…?", "mira qué hay en la tabla…"), no lo
   hagas desde aquí aunque técnicamente pudieras. Explica que en Sofibot los datos se
   consultan con el conector **Sofibot consultas**, que aplica los permisos de cada usuario y
   registra cada consulta (se configura en la parte D de "Después de arrancar"), y que los
   informes se crean con el conector **Sofibot informes**.
6. Si una regla te impide ayudar en algo, dilo, di qué regla es y propón la alternativa: que
   la persona ejecute el paso y te cuente solo si ha ido bien o el mensaje de error.

### Qué puedes ejecutar tú

Solo comandos que no tocan secretos ni datos: `docker version`, `docker compose version`,
`docker compose pull`, `docker compose ps`, `docker compose up -d`, `docker compose down`,
`docker compose restart`, descomprimir el paquete y listar carpetas. Puedes leer los `.md`
del paquete, las plantillas `.env*.example`, `compose.yaml`, `caddy/Caddyfile`,
`sql/crear-login-lectura.sql` y `reports/gold_schema.json` (solo estructura: nombres de
tablas y columnas, sin datos).

### Qué hace siempre la persona

Lo marcado como **👤 Persona** en los pasos: el `docker login`, editar `.env` y
`.env.consultas`, y los comandos `docker compose run …` (`sofibot config`, `sofibot check`,
`sofibot schema`). Después te dice si ha ido bien o te pega el mensaje. La salida de
`sofibot config` está pensada para enseñártela: solo dice qué variables están rellenas o
faltan, nunca sus valores.

---

## Pasos

Antes de empezar, pregunta a la persona:

1. **¿Es el servidor de producción?** Si lo es, díselo claramente: Datasofi recomienda **no
   usar asistentes de IA en el servidor de producción**. Ofrécele seguir desde su PC: tú le
   das los comandos y ella te pega solo los mensajes de error (nunca contraseñas ni datos).
   Si aun así quiere seguir aquí, continúa con las reglas y, al terminar el paso 7, guíala
   por *Producción en Linux: secretos fuera de la carpeta* de `INSTALAR.md`: después de eso
   tú ya no podrás leer las contraseñas ni usar Docker, y es lo que se pretende.
2. **¿Linux o Windows** (con Docker Desktop)? Usa los comandos de ese sistema. Para
   producción se recomienda Linux; Windows sirve para probar.
3. **¿Qué cuenta de IA usa?** Recomiéndale la cuenta de empresa aprobada, no una personal.

### Paso 0 · Requisitos

- **Linux**: Docker instalado. Si no lo está, pasos 1 a 3 de
  [00 · Instalación paso a paso en Debian](00-instalacion-debian-paso-a-paso.md) (no el paso 4).
- **Windows**: Docker Desktop instalado y arrancado. Si Docker Desktop dice *WSL not
  installed*, la persona abre *Terminal (Administrador)*, ejecuta `wsl --install --no-distribution`
  y reinicia el equipo.
- El **login de solo lectura** de SQL Server, creado por el DBA con `sql/crear-login-lectura.sql`
  (el script trae las instrucciones en su cabecera). La persona debe tener el usuario y la
  contraseña: **no se los pidas**.

✅ **Bien si** `docker version` muestra un bloque *Client* y otro *Server*.

### Paso 1 · Descomprimir el paquete

Linux:
```bash
sudo mkdir -p /opt/sofibot && sudo chown $USER:$USER /opt/sofibot
tar -xzf sofibot-eqz-<versión>.tar.gz -C /opt/sofibot --strip-components=1
cd /opt/sofibot
```
Windows (PowerShell):
```powershell
mkdir C:\sofibot
tar -xzf sofibot-eqz-<versión>.tar.gz -C C:\sofibot --strip-components=1
cd C:\sofibot
```

✅ **Bien si** en la carpeta están `compose.yaml`, `.env.example`, `INSTALAR.md`, `docs`, `sql`…

### Paso 2 · 👤 Persona: acceso al registro de imágenes

```bash
docker login ghcr.io -u <usuario que ha dado Datasofi>
```
Como contraseña pega el token de solo lectura de Datasofi (no se ve al pegarlo).

✅ **Bien si** dice `Login Succeeded`. ❌ `unauthorized` o `denied`: usuario o token
incorrectos o caducados; pedir uno nuevo a Datasofi.

### Paso 3 · 👤 Persona: configurar `.env`

```bash
cp .env.example .env
nano .env            # Windows: notepad .env
```

Explícale qué rellenar sin ver el fichero (las explicaciones están en `.env.example`):

| Variable | Qué poner |
|---|---|
| `SQLSERVER_HOST` | Nombre o IP del SQL Server. Si está en el mismo equipo: `host.docker.internal` |
| `SQLSERVER_DATABASE` | La base de datos |
| `SQLSERVER_USER`, `SQLSERVER_PASSWORD` | El login de solo lectura que ha creado el DBA |
| `SQLSERVER_GOLD_SCHEMA` | El esquema de las tablas Gold (`gold`, o el que use la empresa) |
| `SQLSERVER_TRUST_CERTIFICATE` | `0`; `1` solo con un SQL Server de prueba sin certificado |
| `SOFIBOT_ADMIN_TOKEN` | Un texto aleatorio de 40 caracteres (ver abajo) |

Para generar el texto aleatorio:
- Linux: `openssl rand -base64 30`
- Windows: `-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | % {[char]$_})`

En Linux, además: `echo "SOFIBOT_UID=$(id -u)" >> .env` y `echo "SOFIBOT_GID=$(id -g)" >> .env`.
Recomiéndale también `chmod 600 .env`, para que solo su usuario pueda leerlo.

### Paso 4 · Descargar la imagen

```bash
docker compose pull
```
✅ **Bien si** termina sin errores. ❌ `denied`/`unauthorized`: repetir el paso 2.
❌ `manifest unknown`: esa versión no está publicada; avisar a Datasofi.

### Paso 5 · 👤 Persona: comprobar la configuración

```bash
docker compose run --rm sofibot sofibot config
```
La persona te pega la salida: solo lleva nombres de variables, `rellena` o `FALTA`.

✅ **Bien si** termina en `Configuración completa`. Si no, cada línea `FALTA:` dice qué
variable corregir en `.env`; vuelve al paso 3 para esa variable.

### Paso 6 · 👤 Persona: probar la conexión y leer el esquema

```bash
docker compose run --rm sofibot sofibot check
docker compose run --rm sofibot sofibot schema
```
✅ **Bien si** `check` termina en `Connection OK` y `schema` dice `Wrote …gold_schema.json`.
Pídele solo eso, o el mensaje de error: **no le pidas el resto de la salida** de `check`.
Si falla, el propio mensaje incluye un `QUÉ HACER`; más casos en
[Solución de problemas](solucion-de-problemas.md) y [02 · Conexión](02-conexion-sql-server.md).
Después ya puedes leer `reports/gold_schema.json` para comprobar que hay tablas.

### Paso 7 · Arrancar

```bash
docker compose up -d
docker compose ps
```
✅ **Bien si** `sofibot` aparece `running (healthy)` (puede tardar un minuto) y
`http://localhost:8080` abre Sofibot en el propio equipo. Si el puerto 8080 está ocupado,
la persona cambia `SOFIBOT_PORT` en `.env` y repite este paso.

### Paso 8 · Solo producción en Linux: secretos fuera de la carpeta

Guíala por la sección *Producción en Linux: secretos fuera de la carpeta* de `INSTALAR.md`:
contraseñas a `/etc/sofibot` (solo root), carpetas de datos solo para el contenedor y Docker
solo con `sudo`. Todos sus comandos los ejecuta la persona (llevan `sudo`). Al terminar, tú
ya no tendrás acceso a Docker: los comandos posteriores también los ejecuta ella, con `sudo`.

### Después de arrancar

Sofibot funciona en el propio equipo. Lo siguiente (HTTPS, Entra ID, consultas, permisos y
conectores) está en [00 · Sofibot completo paso a paso](00-sofibot-completo-paso-a-paso.md).
Puedes guiar a la persona con esa guía aplicando las mismas reglas: los secretos de Entra ID
van en `.env` y `.env.consultas` y los pone ella; para el servicio de consultas, el
comprobador es `docker compose run --rm consultas sofibot config --consultas`, que ejecuta
ella y te pega la salida. Donde la guía diga `docker compose build`, no hace falta.

---

## Qué protege a los datos (para la persona)

Las reglas anteriores son **instrucciones** para el asistente. Las protecciones de verdad son
estas:

| Capa | Protección |
|---|---|
| Informes y consultas de Sofibot (API, permisos por rol, catálogo, registro) | **Bloqueo real** en el servidor: ningún asistente puede saltárselo |
| Base de datos (logins que solo leen las tablas Gold o el catálogo) | **Bloqueo real** en SQL Server |
| Esta carpeta con **Claude Code** | **Bloqueo real**: `.claude/settings.json` le impide leer `.env` y los datos y ejecutar los comandos peligrosos |
| Esta carpeta con **Codex** u otros asistentes | **Instrucción** (`AGENTS.md`): suelen seguirla, pero no es una barrera. Revisa cada comando antes de aprobarlo |
| Servidor Linux con *Producción en Linux* aplicado | **Bloqueo real** del sistema operativo: tu usuario ya no lee las contraseñas, los datos ni usa Docker sin `sudo` |
| Siempre | Lo que toca contraseñas o la base lo ejecutas tú, no el asistente |

Datasofi recomienda no usar asistentes de IA en el servidor de producción: lo más seguro es
instalar siguiendo `INSTALAR.md` y, si necesitas ayuda, pegarle solo los mensajes de error a un
asistente en tu PC, con la cuenta de empresa.

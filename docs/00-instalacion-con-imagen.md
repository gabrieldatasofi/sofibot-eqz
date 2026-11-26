# 00 · Instalación con imagen publicada (`docker compose pull`)

Instalación de Sofibot **sin código fuente**: Datasofi publica cada versión como una imagen
Docker ya construida y probada, y vuestro servidor la descarga. Solo configuráis `.env`,
`.env.consultas` y la carpeta `reports/`; el programa no se puede modificar, y vuestra
instalación es idéntica a la que Datasofi ha probado.

Sirve igual en un servidor Linux y en un PC con Windows y Docker Desktop: cada paso trae los
comandos de los dos. Tiempo aproximado: 20 minutos, más lo que tarde el DBA en crear el login.

> **Linux para producción, Windows para probar.** Para el uso diario se recomienda un
> servidor Linux. Un PC con Windows y Docker Desktop sirve para probar, pero no como
> servidor: se apaga o se suspende, y Docker no arranca hasta que alguien inicia sesión.
> Docker Desktop tampoco está soportado en Windows Server. Además, Docker Desktop solo es
> gratuito para empresas pequeñas (hoy, menos de 250 empleados y menos de 10 millones de
> facturación anual); las demás necesitan una suscripción de pago: revisad las condiciones
> de Docker antes de usarlo.

> En los bloques de comandos, lo que va entre `< >` lo sustituyes tú (sin los `< >`).

> **¿Instaláis con ayuda de un asistente de IA (Claude Code, Codex…)?** Abrid la carpeta del
> paquete con él y pedidle que siga `INSTALAR-CON-IA.md`: os guía paso a paso sin ver vuestras
> contraseñas ni vuestros datos. Lee antes [Asistentes de IA y esta carpeta](#asistentes-de-ia-y-esta-carpeta).

---

## Qué os entrega Datasofi

| Qué | Para qué |
|---|---|
| `sofibot-eqz-<versión>.tar.gz` | El paquete de instalación: `compose.yaml`, plantillas de configuración, `Caddyfile`, el script SQL para el DBA (`sql/crear-login-lectura.sql`), las plantillas de secretos para producción (`secretos.env.example`), la documentación, `INSTALAR-CON-IA.md` y las reglas para asistentes de IA. **No contiene el código del programa**, que va dentro de la imagen |
| Un usuario de GitHub y un **token de solo lectura** | Descargar la imagen del registro privado de Datasofi (`ghcr.io`). Solo permite descargar |
| La contraseña de **`supersofi`**, aparte | La cuenta de pruebas que ya viene en el paquete (`acceso/cuentas-locales.json`, solo su *hash*): entra con usuario y contraseña, sin Entra ID, con todos los roles |

El `compose.yaml` del paquete apunta a la versión exacta de la imagen por su huella
(`@sha256:…`): aunque alguien publicara otra imagen con el mismo nombre, vuestro servidor
descargaría siempre la probada.

## Antes de empezar

- **Servidor Linux**: Docker instalado. Seguid los pasos 1 a 3 de
  [00 · Instalación paso a paso en Debian](00-instalacion-debian-paso-a-paso.md) (entrar,
  herramientas básicas e instalar Docker) y volved aquí. **No hagáis el paso 4** (descargar
  el código): con esta forma no hace falta.
- **PC con Windows**: Docker Desktop instalado y arrancado.
- El **login de solo lectura** de SQL Server, ya creado por el DBA. El script que lo crea
  está en el paquete, en `sql/crear-login-lectura.sql`: es un fichero de texto que se abre
  con SSMS o VS Code, no hace falta el resto del paquete. **Enviádselo al DBA antes de
  empezar**: tiene las instrucciones en su cabecera (cambiar la contraseña y la base de datos
  y ejecutarlo) y os devuelve el usuario y la contraseña para el paso 3. Si vais a usar las
  consultas, el mismo script crea el segundo login (`sofibot_consultas`).
- Que el equipo llegue al SQL Server por red ([02 · Conexión](02-conexion-sql-server.md)).

---

## Paso 1 · Descomprimir el paquete

**Linux:**

```bash
sudo mkdir -p /opt/sofibot
sudo chown $USER:$USER /opt/sofibot
tar -xzf sofibot-eqz-<versión>.tar.gz -C /opt/sofibot --strip-components=1
cd /opt/sofibot
ls
```

**Windows (PowerShell):**

```powershell
mkdir C:\sofibot
tar -xzf sofibot-eqz-<versión>.tar.gz -C C:\sofibot --strip-components=1
cd C:\sofibot
dir
```

✅ **Bien si** veis `compose.yaml`, `.env.example`, `INSTALAR.md`, `caddy`, `docs`, `reports`, `sql`…

## Paso 2 · Acceso al registro de imágenes

```bash
docker login ghcr.io -u <usuario que os ha dado Datasofi>
```

Como contraseña, pegad el **token** (no se ve al pegarlo) y pulsad Enter.

✅ **Bien si** dice `Login Succeeded`. Docker lo recuerda: no hay que repetirlo.

❌ **Si no**: `unauthorized` o `denied` → el usuario o el token no son correctos, o el token
ha caducado: pedid uno nuevo a Datasofi.

## Paso 3 · Configurar

```bash
cp .env.example .env
nano .env                      # en Windows: notepad .env
```

Rellenad la conexión a SQL Server (`SQLSERVER_HOST`, `SQLSERVER_DATABASE`,
`SQLSERVER_USER`, `SQLSERVER_PASSWORD`…) y `SOFIBOT_ADMIN_TOKEN`. Cada variable está
explicada en el propio fichero y en [Configuración](configuracion.md). En Linux, para que el
contenedor pueda escribir en las carpetas: `echo "SOFIBOT_UID=$(id -u)" >> .env` y
`echo "SOFIBOT_GID=$(id -g)" >> .env`.

## Paso 4 · Descargar la imagen y comprobar la conexión

```bash
docker compose pull
docker compose run --rm sofibot sofibot config
docker compose run --rm sofibot sofibot check
docker compose run --rm sofibot sofibot schema
```

✅ **Bien si** `pull` descarga sin errores, `config` termina con `Configuración completa`,
`check` termina con `Connection OK` y `schema` escribe `reports/gold_schema.json`.

❌ **Si no**:
- `pull` dice `denied` o `unauthorized` → repetid el paso 2.
- `pull` dice `manifest unknown` → esa versión no está publicada: avisad a Datasofi.
- `config` dice `FALTA: …` → corregid esa variable en `.env` (paso 3). `config` nunca
  muestra los valores, solo si cada variable está rellena: su salida se puede enseñar a
  quien os ayude.
- `check` falla → el mensaje dice qué hacer; más casos en [Solución de problemas](solucion-de-problemas.md).

## Paso 5 · Arrancar

```bash
docker compose up -d
docker compose ps
```

✅ **Bien si** `sofibot` aparece `running (healthy)` y `http://localhost:8080` (desde el propio
equipo) abre Sofibot.

## Producción en Linux: secretos fuera de la carpeta

**Recomendado para el servidor de producción.** Con la instalación anterior, el usuario que
instala tiene en su carpeta las contraseñas (`.env`) y puede usar Docker. Quien entre con ese
usuario, o un asistente de IA que trabaje con él, puede leer las contraseñas y llegar a los
datos por fuera de Sofibot. Estos pasos lo convierten en una barrera del sistema operativo:
las contraseñas y los datos solo los lee root, y Docker solo se usa con `sudo`, que pide la
contraseña del administrador.

Cuando Sofibot ya funcione (paso 5), desde `/opt/sofibot`:

**1 · Contraseñas y tokens a `/etc/sofibot`, solo para root:**

```bash
sudo mkdir -p /etc/sofibot
sudo chmod 700 /etc/sofibot
sudo cp secretos.env.example /etc/sofibot/secretos.env
sudo chmod 600 /etc/sofibot/secretos.env
sudo nano /etc/sofibot/secretos.env
```

Poned ahí `SQLSERVER_PASSWORD`, `SOFIBOT_ADMIN_TOKEN` y, si los usáis, `ENTRA_CLIENT_SECRET`,
`SOFIBOT_VIEWER_PASSWORD` o `SOFIBOT_API_TOKEN`. Después, **dejad esas variables vacías en
`.env`** (`nano .env`). Lo que hay en `secretos.env` tiene prioridad sobre `.env`.

Con el servicio de consultas, igual con `secretos-consultas.env.example` →
`/etc/sofibot/secretos-consultas.env` (su `SQLSERVER_PASSWORD`, la del login
`sofibot_consultas`), y dejad vacía `SQLSERVER_PASSWORD` en `.env.consultas`.

**2 · Las carpetas con datos, solo para el contenedor:**

```bash
sed -i '/^SOFIBOT_UID=/d;/^SOFIBOT_GID=/d' .env
mkdir -p acceso consultas
sudo chown -R 10001:10001 reports output acceso consultas
sudo chmod 700 output acceso consultas
```

El contenedor usa su propio usuario (10001): los informes generados (`output/`), los usuarios
y sus roles (`acceso/`) y el registro de consultas (`consultas/`) dejan de ser legibles para
vuestro usuario. `reports/` sigue
legible (código de los informes y estructura, sin datos), pero ya solo se modifica desde el
portal o con `sudo`.

**3 · Docker solo con `sudo`:**

```bash
sudo gpasswd -d $USER docker
exit
```

Volved a entrar por `ssh`. Desde ahora, todos los comandos `docker compose …` de las guías
van con `sudo` delante: `sudo docker compose up -d`, `sudo docker compose run --rm sofibot sofibot config`…

**4 · Comprobar:**

```bash
sudo docker compose up -d
sudo docker compose run --rm sofibot sofibot config
cat /etc/sofibot/secretos.env
docker ps
```

✅ **Bien si** `config` termina en `Configuración completa`, y `cat` y `docker ps` (sin `sudo`)
responden *Permission denied*: vuestro usuario, y cualquier asistente que trabaje con él, ya
no llega a las contraseñas ni a Docker.

❌ **Si** `docker compose` dice *permission denied* al leer `/etc/sofibot/…` → os habéis dejado
el `sudo` delante.

En Windows con Docker Desktop, para pruebas, no hace falta: allí la configuración se queda en
la carpeta.

---

## Después de arrancar

Sofibot ya funciona en el propio equipo. Para empezar a probar, entrad en el portal con la
cuenta de pruebas **`supersofi`** (usuario y contraseña, sin Microsoft): tiene todos los roles
y todas las tablas. Con `SOFIBOT_AUTH=local` en `.env` no hace falta configurar Entra ID; para
que sus conectores de Claude o Codex y la página Consultas funcionen, rellenad también
`SOFIBOT_LOCAL_SECRET` (en `.env` y `.env.consultas`, el mismo valor). Detalle:
[09 · Cuentas locales](09-inicio-sesion-entra.md#cuentas-locales-sin-entra-id).

Para que lo use vuestra gente queda configurar, en
este orden, lo que explica con detalle [00 · Sofibot completo paso a paso](00-sofibot-completo-paso-a-paso.md)
(en la carpeta `docs/` del paquete):

| Parte | Quién | Qué |
|---|---|---|
| **A · HTTPS** | Sistemas | Un nombre en el DNS (por ejemplo `informes.empresa.local`), un certificado y el proxy activado, para entrar desde otros PCs |
| **B · Entra ID** | Administrador de Entra ID | Una checklist: registrar la aplicación, secreto, exponer la API, cliente público y consentimiento. Entra ID solo valida el inicio de sesión: los roles se dan en Sofibot |
| **C · Inicio de sesión e informes con IA** | Sistemas | Añadir al `.env` los datos de Entra ID y `docker compose up -d` |
| **D · Consultas** | DBA, Sistemas y Datasofi | Segundo login (`sofibot_consultas`), `.env.consultas`, el catálogo de consultas que prepara Datasofi y activar el servicio |
| **E · Permisos y usuarios** | Administrador de Sofibot | En el portal, **Administración → Permisos**: qué tablas ve cada rol. Después, cada usuario conecta su Claude o Codex desde **Conectar tu IA** |

En esa guía, donde diga `docker compose up -d` sirve tal cual. `docker compose build` no
hace falta nunca con esta forma de instalar.

---

## Actualizar a una versión nueva

Datasofi os entrega el paquete de la versión nueva:

1. Descomprimidlo en otra carpeta y copiad **solo** su `compose.yaml` encima del vuestro
   (y `docs/`, si queréis la documentación nueva). **No toquéis** `.env`, `.env.consultas`,
   `reports/`, `output/`, `acceso/`, `consultas/` ni `caddy/certs/`: son vuestros. Única
   excepción, al pasar de una versión sin cuentas locales (0.2.1 o anterior) a la 0.2.2: si
   vuestra `acceso/` no tiene `cuentas-locales.json`, copiad el del paquete para tener
   `supersofi`.
2. Descargad y arrancad:

   ```bash
   docker compose pull
   docker compose up -d
   ```

Para volver a la versión anterior, poned su `compose.yaml` y repetid el paso 2.

## Varias instalaciones en el mismo equipo

El proyecto se llama `sofibot-eqz` (lo fija el `compose.yaml`), así que puede convivir con
otras aplicaciones Docker, por ejemplo otra instalación de Sofibot. Si el puerto 8080 está
ocupado, cambiad en `.env` `SOFIBOT_PORT` (y `SOFIBOT_QUERY_PORT`, si usáis consultas). El
proxy HTTPS usa los puertos 80 y 443: si ya hay otro proxy en el equipo, no activéis el
perfil `https` y añadid Sofibot a ese proxy ([08 · HTTPS](08-acceso-https.md)).

## Asistentes de IA y esta carpeta

> **Recomendación de Datasofi: no uséis asistentes de IA (Claude Code, Codex, Copilot…) en el
> servidor de producción.** Si queréis ayuda de una IA para instalar o resolver un problema,
> usadla en vuestro PC y pegadle solo los comandos y los mensajes de error, nunca contraseñas
> ni resultados con datos. Usad siempre la cuenta de empresa de Claude u OpenAI que hayáis
> aprobado, no una personal: con una cuenta personal, el proveedor puede guardar las
> conversaciones o usarlas para entrenar sus modelos, según su configuración. Como barrera
> técnica, seguid [Producción en Linux: secretos fuera de la carpeta](#producción-en-linux-secretos-fuera-de-la-carpeta).

La carpeta de instalación contiene las contraseñas del SQL Server (`.env`, `.env.consultas`)
y, con Docker, da acceso a la base. Un asistente de IA abierto en ella trabaja con vuestros
permisos: si nada se lo impide, puede leer `.env` y consultar la base **por fuera de
Sofibot**, sin permisos por usuario, sin registro y enviando los datos a su proveedor. Por
eso el paquete trae:

| Fichero | Para quién | Qué hace |
|---|---|---|
| `INSTALAR-CON-IA.md` | Cualquier asistente | Guion de instalación: qué ejecuta el asistente y qué ejecutáis vosotros (todo lo que toca contraseñas o la base) |
| `AGENTS.md` | Codex y otros | Las reglas: no leer `.env` ni datos, no ejecutar nada contra la base. Es una **instrucción**, no un bloqueo |
| `CLAUDE.md` y `.claude/settings.json` | Claude Code | Las mismas reglas y, además, **bloqueos reales**: Claude Code no puede leer esos ficheros ni ejecutar `sqlcmd`, `docker compose run`, `docker exec`… |

No borréis ni editéis estos ficheros. Con Codex u otros asistentes, revisad cada comando
antes de aprobarlo. Lo más seguro sigue siendo instalar sin asistente, o pegarle solo los
mensajes de error a uno que no tenga acceso a la carpeta.

Para consultar datos con IA, la vía es el conector **Sofibot consultas** (parte D de
*Después de arrancar*): aplica los permisos de cada usuario y registra cada consulta. Las
protecciones de cada funcionalidad están en [06 · Seguridad](06-seguridad.md).

Estos ficheros son la red de seguridad para pruebas y despistes. En producción, la barrera
real es la de [Producción en Linux](#producción-en-linux-secretos-fuera-de-la-carpeta): con
ella, el usuario de trabajo no llega ni a las contraseñas ni a Docker.

## Qué queda en vuestro equipo

| Carpeta o fichero | Qué es | Copia de seguridad |
|---|---|---|
| `.env`, `.env.consultas` | Configuración (y contraseñas, si no usáis `/etc/sofibot`) | Sí, en un gestor de secretos |
| `/etc/sofibot/` | Contraseñas y tokens en producción Linux | Sí, en un gestor de secretos |
| `reports/` | Vuestros informes, catálogo, permisos y registros | Sí |
| `consultas/` | Registro de consultas | Sí |
| `output/` | Informes generados | No: se regeneran |
| `compose.yaml`, `docs/` | Del paquete de Datasofi | No: vienen en cada versión |

---

## Para Datasofi: publicar una versión y dar acceso al cliente

**Publicar** (en el equipo Windows de Datasofi, con Docker Desktop y Python 3.12):

```powershell
docker login ghcr.io -u <tu usuario de GitHub>   # una vez; contraseña: token clásico con write:packages
.\publicar-imagen.ps1
```

El script comprueba el `.exe` de los conectores, construye la imagen, pasa los tests dentro
de ella (si fallan, no publica), la sube a `ghcr.io/gabrieldatasofi/sofibot-eqz:<versión>` y
genera `dist-instalacion/sofibot-eqz-<versión>.tar.gz`, que es lo que se entrega.
`.\publicar-imagen.ps1 -SinSubir` hace todo menos subirla, para probar.

**Dar acceso de solo lectura al cliente:**

1. Una cuenta de GitHub para el cliente o para entregas (por ejemplo `datasofi-entregas`),
   no la de una persona de Datasofi.
2. En GitHub, el paquete `sofibot-eqz` (perfil → *Packages*) →
   *Package settings* → *Manage access* → añadir esa cuenta con rol **Read**. El paquete
   es privado: hereda la visibilidad del repositorio.
3. Con esa cuenta: *Settings → Developer settings → Personal access tokens → Tokens
   (classic)* → nuevo token solo con **`read:packages`**, con caducidad. A día de hoy, los
   tokens *fine-grained* de GitHub no sirven para el registro de imágenes.
4. Entregar el usuario y el token por un canal seguro, nunca por correo, junto con el paquete.

**Dar acceso al código** (repositorio privado `github.com/gabrieldatasofi/sofibot-eqz`):

| Quién | Cómo | Permiso |
|---|---|---|
| Quien desarrolla con Datasofi | Repositorio → *Settings → Collaborators → Add people* | **Write** (push, ramas, pull requests). Si también publica la imagen: en el paquete, *Package settings → Manage access* con rol **Write** |
| Un servidor con la instalación de desarrollo (`git clone`) | Repositorio → *Settings → Deploy keys → Add deploy key* con la clave pública del servidor ([guía de Debian, paso 4](00-instalacion-debian-paso-a-paso.md#paso-4--descargar-sofibot)) | Solo lectura: no marcar *Allow write access* |
| Quien solo instala y usa Sofibot | No necesita el código: imagen publicada y token de lectura (arriba) | — |

Retirar el acceso es borrar al colaborador o la clave de despliegue. Las contraseñas y
tokens de cada instalación no están en el repositorio, así que no hay que cambiarlas.

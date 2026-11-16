# 00 · Instalación con imagen publicada (`docker compose pull`)

Instalación de Sofibot **sin código fuente**: Datasofi publica cada versión como una imagen
Docker ya construida y probada, y vuestro servidor la descarga. Solo configuráis `.env`,
`.env.consultas` y la carpeta `reports/`; el programa no se puede modificar, y vuestra
instalación es idéntica a la que Datasofi ha probado.

Sirve igual en un servidor Linux (recomendado) y en un PC con Windows y Docker Desktop
(para probar). Tiempo aproximado: 20 minutos, más lo que tarde el DBA en crear el login.

> En los bloques de comandos, lo que va entre `< >` lo sustituyes tú (sin los `< >`).

---

## Qué os entrega Datasofi

| Qué | Para qué |
|---|---|
| `sofibot-eqz-<versión>.tar.gz` | El paquete de instalación: `compose.yaml`, plantillas de configuración, `Caddyfile`, el script SQL para el DBA (`sql/crear-login-lectura.sql`) y la documentación. **No contiene el código del programa**, que va dentro de la imagen |
| Un usuario de GitHub y un **token de solo lectura** | Descargar la imagen del registro privado de Datasofi (`ghcr.io`). Solo permite descargar |

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
docker compose run --rm sofibot sofibot check
docker compose run --rm sofibot sofibot schema
```

✅ **Bien si** `pull` descarga sin errores, `check` termina con `Connection OK` y `schema`
escribe `reports/gold_schema.json`.

❌ **Si no**:
- `pull` dice `denied` o `unauthorized` → repetid el paso 2.
- `pull` dice `manifest unknown` → esa versión no está publicada: avisad a Datasofi.
- `check` falla → el mensaje dice qué hacer; más casos en [Solución de problemas](solucion-de-problemas.md).

## Paso 5 · Arrancar

```bash
docker compose up -d
docker compose ps
```

✅ **Bien si** `sofibot` aparece `running (healthy)` y `http://localhost:8080` (desde el propio
equipo) abre Sofibot.

---

## Después de arrancar

Sofibot ya funciona en el propio equipo. Para que lo use vuestra gente queda configurar, en
este orden, lo que explica con detalle [00 · Sofibot completo paso a paso](00-sofibot-completo-paso-a-paso.md)
(en la carpeta `docs/` del paquete):

| Parte | Quién | Qué |
|---|---|---|
| **A · HTTPS** | Sistemas | Un nombre en el DNS (por ejemplo `informes.empresa.local`), un certificado y el proxy activado, para entrar desde otros PCs |
| **B · Entra ID** | Administrador de Entra ID | Una checklist: registrar la aplicación, secreto, roles, exponer la API, cliente público, consentimiento y asignar los roles a grupos |
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
   `reports/`, `output/`, `consultas/` ni `caddy/certs/`: son vuestros.
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

## Qué queda en vuestro equipo

| Carpeta o fichero | Qué es | Copia de seguridad |
|---|---|---|
| `.env`, `.env.consultas` | Configuración y contraseñas | Sí, en un gestor de secretos |
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
2. En GitHub, el paquete `sofibot-eqz` (perfil → *Packages*) → *Package settings* →
   *Manage access* → añadir esa cuenta con rol **Read**. El paquete es privado: hereda la
   visibilidad del repositorio.
3. Con esa cuenta: *Settings → Developer settings → Personal access tokens → Tokens
   (classic)* → nuevo token solo con **`read:packages`**, con caducidad. A día de hoy, los
   tokens *fine-grained* de GitHub no sirven para el registro de imágenes.
4. Entregar el usuario y el token por un canal seguro, nunca por correo, junto con el paquete.

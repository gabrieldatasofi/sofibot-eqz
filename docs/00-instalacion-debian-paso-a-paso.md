# 00 · Instalación paso a paso en un servidor Debian

Guía para instalar Sofibot en un servidor **Debian 12 o 13 recién instalado**, sin
conocimientos previos de Docker. Cada paso tiene los comandos para copiar y pegar, lo que
deberías ver si ha ido bien y qué hacer si no.

Tiempo aproximado: 30 minutos, más lo que tarde el DBA en crear el login (paso 6).

> En los bloques de comandos, copia las líneas tal cual. Lo que va entre `< >` lo
> sustituyes tú (sin los `< >`). Las líneas que empiezan por `#` son comentarios.

---

## Antes de empezar: qué necesitas

| Qué | Para qué | Quién te lo da |
|---|---|---|
| Un servidor Debian 12 o 13 (2 vCPU, 4 GB de RAM, 10 GB de disco) con salida a internet | Donde va Sofibot | Sistemas |
| Un usuario con permiso de administrador (`sudo`) y acceso por SSH | Instalar | Sistemas |
| Acceso al repositorio de GitHub de Sofibot | Descargar el código | Datasofi (ver paso 4) |
| Nombre del SQL Server, puerto, base de datos y esquema Gold | Conectar | DBA |
| El login de solo lectura creado con `sql/crear-login-lectura.sql` | Conectar | DBA (paso 6) |
| Que el servidor de Sofibot llegue al SQL Server por red | Conectar | Sistemas / redes |

---

## Paso 1 · Entrar en el servidor

Desde tu PC (en Windows: abre **PowerShell**; en Mac o Linux: **Terminal**):

```bash
ssh <usuario>@<ip-o-nombre-del-servidor>
```

✅ **Bien si** ves algo como `<usuario>@<servidor>:~$`.

❌ **Si no**: `Connection refused` o `timed out` → el servidor no es accesible por SSH desde
tu red; pregunta a sistemas.

Todos los pasos siguientes se ejecutan **dentro del servidor**.

---

## Paso 2 · Herramientas básicas

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git nano openssl netcat-openbsd
```

✅ **Bien si** termina sin líneas que empiecen por `E:`.

❌ **Si no**:
- `sudo: command not found` → estás como `root` en un Debian mínimo. Ejecuta los comandos
  **sin** la palabra `sudo` (en esta guía y en las siguientes), o instala sudo con
  `apt-get install -y sudo`.
- `<usuario> is not in the sudoers file` → tu usuario no es administrador; pide a sistemas
  que lo añada (`usermod -aG sudo <usuario>`) o que te den acceso como root.
- Errores de red al descargar → el servidor no tiene salida a internet. Ver "Instalación sin
  internet" en [01 · Instalación](01-instalacion.md).

---

## Paso 3 · Instalar Docker

Copia el bloque entero de una vez:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Permite que tu usuario use Docker sin `sudo`:

```bash
sudo usermod -aG docker $USER
```

**Sal del servidor (`exit`) y vuelve a entrar con `ssh`** para que el cambio se aplique.
Después comprueba:

```bash
docker run --rm hello-world
docker compose version
```

✅ **Bien si** el primero muestra `Hello from Docker!` y el segundo `Docker Compose version v2...` o superior.

❌ **Si no**:
- `permission denied while trying to connect to the Docker daemon socket` → no has salido y
  vuelto a entrar tras el `usermod`.
- `Cannot connect to the Docker daemon` → arranca Docker: `sudo systemctl enable --now docker`.

> No instales el paquete `docker.io` de Debian: no incluye `docker compose`.

---

## Paso 4 · Descargar Sofibot

El repositorio es privado. La forma recomendada para un servidor es una **clave de
despliegue**: una clave que solo sirve para leer este repositorio desde este servidor.

**4.1 · Crear la clave en el servidor:**

```bash
ssh-keygen -t ed25519 -C "sofibot-servidor" -f ~/.ssh/sofibot_deploy -N ""
cat ~/.ssh/sofibot_deploy.pub
```

Copia la línea que empieza por `ssh-ed25519` y **envíasela a Datasofi**. Es la parte pública:
se puede enviar por correo sin problema. **Nunca envíes el fichero sin `.pub`.**

Datasofi la añade al repositorio como clave de solo lectura y te avisa.

**4.2 · Configurar SSH para usar esa clave con GitHub** (un único bloque):

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
    IdentityFile ~/.ssh/sofibot_deploy
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

**4.3 · Descargar el código en `/opt/sofibot`:**

```bash
sudo mkdir -p /opt/sofibot
sudo chown $USER:$USER /opt/sofibot
git clone git@github.com:gabrieldatasofi/sofibot-eqz.git /opt/sofibot
cd /opt/sofibot
ls
```

La primera vez pregunta `Are you sure you want to continue connecting (yes/no)?`: escribe
`yes` y pulsa Intro.

✅ **Bien si** `ls` muestra `README.md`, `compose.yaml`, `docs`, `sql`, `src`…

❌ **Si no**: `Permission denied (publickey)` → Datasofi aún no ha añadido la clave, o la
línea copiada estaba incompleta. Comprueba con `ssh -T git@github.com`: debe responder
`Hi gabrieldatasofi/sofibot-eqz! You've successfully authenticated`.

> Alternativa sin clave: si Datasofi te ha invitado al repositorio con tu cuenta de GitHub,
> puedes clonar por HTTPS (`git clone https://github.com/gabrieldatasofi/sofibot-eqz.git /opt/sofibot`)
> usando como contraseña un *personal access token* de tu cuenta (GitHub → Settings →
> Developer settings → Personal access tokens), no tu contraseña de GitHub.

---

## Paso 5 · Comprobar que el servidor llega al SQL Server

```bash
nc -vz <servidor-sql> 1433
```

(Cambia `1433` si vuestro SQL Server usa otro puerto.)

✅ **Bien si** dice `succeeded` u `open`.

❌ **Si no**:
- `timed out` → un firewall o la falta de VPN impiden la conexión. Sistemas o redes deben
  abrir el puerto del SQL Server para la IP de este servidor.
- `Connection refused` → el servidor responde, pero SQL Server no escucha en ese puerto:
  TCP/IP desactivado en SQL Server o puerto distinto.
- `Name or service not known` → el nombre no se resuelve desde este servidor: prueba con la IP.

**No sigas hasta que este paso funcione**: sin él, Sofibot no puede conectar.

---

## Paso 6 · Login de solo lectura (lo hace el DBA)

El DBA ejecuta `sql/crear-login-lectura.sql` en el SQL Server. Puede descargarlo de GitHub
o pedírtelo (está en `/opt/sofibot/sql/`). Instrucciones en
[02 · Conexión](02-conexion-sql-server.md), apartado 1.

Te tiene que pasar: **usuario**, **contraseña**, **nombre de la base de datos** y **esquema
Gold** (normalmente `gold`).

---

## Paso 7 · Configurar Sofibot (`.env`)

```bash
cd /opt/sofibot
cp .env.example .env
chmod 600 .env
echo "SOFIBOT_UID=$(id -u)" >> .env
echo "SOFIBOT_GID=$(id -g)" >> .env
openssl rand -base64 36
```

El último comando muestra un texto aleatorio: cópialo, será el token de administración.

Abre el fichero con el editor:

```bash
nano .env
```

Cambia estas líneas (muévete con las flechas del teclado):

| Línea | Qué poner |
|---|---|
| `SQLSERVER_HOST=` | Nombre o IP del SQL Server (el mismo del paso 5). **Borra** `host.docker.internal` |
| `SQLSERVER_PORT=` | Puerto (normalmente `1433`) |
| `SQLSERVER_DATABASE=` | Base de datos (paso 6) |
| `SQLSERVER_USER=` | Usuario (paso 6) |
| `SQLSERVER_PASSWORD=` | Contraseña (paso 6) |
| `SQLSERVER_GOLD_SCHEMA=` | Esquema Gold (paso 6) |
| `SOFIBOT_ADMIN_TOKEN=` | El texto aleatorio que acabas de copiar |

Guarda y sal: **Ctrl+O**, **Intro**, **Ctrl+X**.

> No pongas comentarios al final de una línea con valor. Si la contraseña tiene `#` o
> espacios, ponla entre comillas: `SQLSERVER_PASSWORD="ab#c d"`.

---

## Paso 8 · Construir Sofibot y probar la conexión

```bash
docker compose build
docker compose run --rm sofibot sofibot check
```

La construcción tarda unos minutos la primera vez.

✅ **Bien si** termina con `Connection OK` y en `"tables"` aparecen vuestras tablas Gold.

❌ **Si no**: el mensaje de error incluye un apartado **QUÉ HACER**. Los casos habituales:

| Mensaje | Qué hacer |
|---|---|
| `certificate verify failed` | El certificado del SQL Server no es de confianza. Lo correcto es que el DBA instale un certificado válido. Mientras tanto, y solo en una red interna controlada, `SQLSERVER_TRUST_CERTIFICATE=1` en `.env` |
| `Login failed` | Usuario o contraseña incorrectos en `.env`, o falta el paso 6 |
| `Login timeout expired` | Vuelve al paso 5 |
| `WARNING: ... sees no tables` | El esquema está vacío o falta el permiso: revisa el paso 6 con el DBA |

Más casos: [Solución de problemas](solucion-de-problemas.md).

---

## Paso 9 · Esquema y primer informe

```bash
docker compose run --rm sofibot sofibot schema
docker compose run --rm sofibot sofibot new prueba --name "Prueba" --table <esquema>.<una-tabla-gold>
docker compose run --rm sofibot sofibot build prueba
```

Para `--table` usa una de las tablas que mostró el paso 8, por ejemplo `gold.ventas_mes_tienda`.

✅ **Bien si** el último comando termina con `Built /app/output/prueba`.

Este informe de prueba exporta la tabla a una página y a un Excel. Cuando ya tengáis los
vuestros, se borra con `rm -rf reports/prueba output/prueba`.

---

## Paso 10 · Arrancar el portal

```bash
docker compose up -d
docker compose ps
```

✅ **Bien si**, tras unos 30 segundos, `docker compose ps` muestra `(healthy)` en la columna
`STATUS` (si pone `starting`, espera y repite).

❌ **Si no**: `port is already allocated` → otro programa usa el puerto 8080. Cambia
`SOFIBOT_PORT=8080` por otro (por ejemplo `8085`) en `.env` y repite `docker compose up -d`.
Para ver qué pasa: `docker compose logs --tail 50`.

---

## Paso 11 · Ver el portal desde tu PC

El portal solo escucha dentro del servidor (más seguro). Para verlo desde tu PC, abre un
**túnel SSH**: en tu PC (no en el servidor), en una ventana nueva de PowerShell o Terminal:

```bash
ssh -L 8080:127.0.0.1:8080 <usuario>@<ip-o-nombre-del-servidor>
```

Deja esa ventana abierta y abre en el navegador de tu PC: **http://localhost:8080**

✅ **Bien si** ves "Sofibot · Informes" con la tarjeta del informe *Prueba*, y puedes abrirlo
y descargar su Excel.

Si cambiaste el puerto en el paso 10, usa ese número en los dos sitios (`-L 8085:127.0.0.1:8085`
y `http://localhost:8085`).

Para que otras personas lo usen sin túnel, ver "Acceso desde la red" en
[05 · Operación](05-operacion.md) (proxy con HTTPS recomendado, y contraseña del portal).

---

## Paso 12 · Comprobar que arranca solo tras un reinicio

```bash
sudo systemctl is-enabled docker
sudo reboot
```

Espera un par de minutos, vuelve a entrar por SSH y:

```bash
cd /opt/sofibot
docker compose ps
```

✅ **Bien si** `is-enabled` dijo `enabled` y tras el reinicio el portal vuelve a estar `(healthy)`.

❌ **Si no**: `sudo systemctl enable --now docker` y `docker compose up -d`.

---

## Listo

Sofibot está instalado. A partir de aquí:

| Quiero… | Dónde |
|---|---|
| Crear informes | [04 · Crear informes](04-crear-informes.md) y [07 · Informes con IA](07-informes-con-ia.md) |
| Regenerar los informes cada día | `SOFIBOT_BUILD_SCHEDULE` en [05 · Operación](05-operacion.md) |
| Publicar el portal para más usuarios | [05 · Operación](05-operacion.md), "Acceso desde la red" |
| Resolver un error | [Solución de problemas](solucion-de-problemas.md) |

### Actualizar a una versión nueva

Cuando Datasofi publique una versión nueva:

```bash
cd /opt/sofibot
git pull
docker compose build
docker compose up -d
docker compose run --rm sofibot sofibot build --all
```

Vuestro `.env` y vuestros informes de `reports/` se conservan.

### Chuleta de comandos

| Comando | Qué hace |
|---|---|
| `cd /opt/sofibot` | Ir a la carpeta de Sofibot (todos los comandos se lanzan desde aquí) |
| `docker compose ps` | Estado del portal |
| `docker compose logs --tail 50` | Últimos mensajes del portal |
| `docker compose restart` | Reiniciar el portal (por ejemplo, tras cambiar `.env`: mejor `docker compose up -d`) |
| `docker compose run --rm sofibot sofibot check` | Probar la conexión con SQL Server |
| `docker compose run --rm sofibot sofibot list` | Listar informes |
| `docker compose run --rm sofibot sofibot build --all` | Regenerar todos los informes |

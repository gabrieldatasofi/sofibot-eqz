# 00 · Sofibot completo paso a paso: HTTPS, Entra ID, informes con IA y consultas

Continuación de [00 · Instalación paso a paso en Debian](00-instalacion-debian-paso-a-paso.md).
Allí queda Sofibot funcionando con el portal de informes. Esta guía añade todo lo demás:

- acceso desde la red con **HTTPS**;
- inicio de sesión de cada persona con su cuenta de **Microsoft Entra ID**;
- **funcionalidad 1**: crear informes con un asistente de IA (Claude o Codex) que nunca ve los datos;
- **funcionalidad 2**: consultar datos desde el portal o con la IA de cada persona;
- la página de **administración**, con los permisos de usuarios y la documentación técnica.

Tiempo aproximado: 1 hora de trabajo, más lo que tarden el administrador de Entra ID
(parte B) y el DBA (paso D1).

> En los bloques de comandos, copia las líneas tal cual. Lo que va entre `< >` lo
> sustituyes tú (sin los `< >`). Todos los comandos del servidor se lanzan desde
> `/opt/sofibot`.

---

## Quién hace qué

| Parte | Quién | Qué |
|---|---|---|
| A · HTTPS | Sistemas | Nombre en el DNS, certificado y proxy |
| B · Entra ID | Administrador de Entra ID | Registrar la aplicación, roles y permisos: una checklist |
| C · Inicio de sesión e informes con IA | Sistemas | Configurar `.env` y probar |
| D · Consultas | DBA y sistemas, con Datasofi | Segundo login, catálogo y servicio de consultas |
| E · Permisos y usuarios | Administrador de Sofibot | Qué tablas ve cada rol, desde el portal |

## Antes de empezar: qué necesitas

| Qué | Para qué | Quién te lo da |
|---|---|---|
| Sofibot instalado con la guía de Debian (pasos 1 a 12) | La base | — |
| Un nombre para el portal, por ejemplo `informes.empresa.local` | HTTPS y Entra ID | Sistemas / DNS |
| Un certificado para ese nombre (o usar la autoridad propia de Caddy) | HTTPS | Sistemas |
| Que el servidor salga a internet por HTTPS hacia `login.microsoftonline.com` | Entra ID | Sistemas / redes |
| Un administrador de Entra ID (rol *Administrador de aplicaciones* o superior) | Parte B | Sistemas |
| La lista de perfiles de acceso a datos (por ejemplo *Dirección*, *Ventas*, *Finanzas*) y qué tablas Gold ve cada uno | Permisos | Negocio / responsable de datos |

---

# Parte A · Acceso con HTTPS (sistemas)

Entra ID exige HTTPS. Resumen de [08 · Acceso desde la red con HTTPS](08-acceso-https.md),
que tiene el detalle de cada opción de certificado.

## Paso A1 · Nombre en el DNS

Da de alta en el DNS interno un nombre que apunte a la IP del servidor, por ejemplo
`informes.empresa.local`.

✅ **Bien si**, desde tu PC, `ping informes.empresa.local` responde con la IP del servidor.

## Paso A2 · Certificado y proxy

```bash
cd /opt/sofibot
nano .env
```

Añade (o cambia) estas líneas:

```ini
COMPOSE_PROFILES=https
SOFIBOT_DOMAIN=informes.empresa.local
# Autoridad propia de Caddy (internal) o certificado corporativo en caddy/certs/:
SOFIBOT_TLS=internal
```

Con certificado corporativo: copia `cert.pem` y `key.pem` a `caddy/certs/` y pon
`SOFIBOT_TLS="/certs/cert.pem /certs/key.pem"`. Guarda (`Ctrl+O`, `Enter`, `Ctrl+X`) y:

```bash
docker compose up -d
```

✅ **Bien si** `https://informes.empresa.local` abre el portal desde tu PC (con `internal`,
antes hay que instalar en los PCs la autoridad de Caddy: [08 · HTTPS](08-acceso-https.md), opción B).

❌ **Si no**: `docker compose logs proxy --tail 30` y [08 · HTTPS](08-acceso-https.md#problemas-frecuentes).

---

# Parte B · Checklist para el administrador de Entra ID

En el [centro de administración de Microsoft Entra](https://entra.microsoft.com), con un
usuario con rol *Administrador de aplicaciones* o superior. Sustituye
`informes.empresa.local` por el nombre del paso A1. Detalle de cada pantalla:
[09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md).

**1. Registrar la aplicación** · *Identidad → Aplicaciones → Registros de aplicaciones → Nuevo registro*

- [ ] Nombre: `Sofibot` (o el que prefiráis).
- [ ] Tipos de cuenta: **Solo las cuentas de este directorio organizativo**.
- [ ] URI de redirección: plataforma **Web**, `https://informes.empresa.local/auth/callback`.
- [ ] Anotar el **Id. de aplicación (cliente)** y el **Id. de directorio (inquilino)**.

**2. Secreto de cliente** · *Certificados y secretos → Nuevo secreto de cliente*

- [ ] Descripción `Servidor Sofibot`, caducidad según vuestra política (por ejemplo 12 meses).
- [ ] Copiar el **Valor** (no el Id.): solo se muestra una vez.
- [ ] Apuntar la fecha de caducidad en un calendario: cuando caduca, nadie puede entrar.

**3. Roles** · *Roles de aplicación → Crear rol de aplicación*, todos con miembros
**Usuarios o grupos**. Lo que cuenta es el **Valor**, exacto:

| Valor | Nombre para mostrar | Para |
|---|---|---|
| `Sofibot.Autor` | Autor de informes | Crear informes con un asistente de IA |
| `Sofibot.Revisor` | Revisor de informes | Revisar, previsualizar y publicar informes |
| `Sofibot.Consultas` | Consultas de datos | Consultar datos |
| `Sofibot.Admin` | Administración de Sofibot | Página de administración: estado, permisos, documentación |
| `Direccion`, `Ventas`… | Uno por perfil de acceso a datos | Qué tablas Gold ve cada persona (sin espacios ni acentos en el valor) |

- [ ] Los cuatro roles `Sofibot.*`.
- [ ] Un rol por cada perfil de acceso a datos.

**4. Exponer la API** · *Exponer una API*

- [ ] **Agregar** el URI de id. de aplicación: dejar el que propone, `api://<id. de cliente>`.
- [ ] **Agregar un ámbito**: nombre `access_as_user`, consentimiento *Administradores y
      usuarios*, nombre para mostrar *Usar Sofibot en nombre del usuario*, estado *Habilitado*.

**5. Cliente público (conectores de Claude y Codex)** · *Autenticación*

- [ ] *Agregar una plataforma → Aplicaciones móviles y de escritorio* con la URI
      personalizada `http://localhost` (sin marcar las sugeridas).
- [ ] *Configuración avanzada → Permitir flujos de clientes públicos: Sí → Guardar*.

**6. Permisos y consentimiento** · *Permisos de API*

- [ ] *Agregar un permiso → Mis API → Sofibot → access_as_user*.
- [ ] **Conceder consentimiento de administrador**. Las filas pasan a "Concedido".

**7. Asignación** · *Identidad → Aplicaciones → Aplicaciones empresariales → Sofibot*

- [ ] *Propiedades → ¿Se requiere asignación?: Sí → Guardar*.
- [ ] *Usuarios y grupos → Agregar*: cada **grupo** (o persona) con sus roles: uno o
      varios de datos y los de funcionalidad que correspondan. Un rol por asignación.
- [ ] Al menos una persona con `Sofibot.Admin` y un rol de datos, para la parte E.

**8. Entregar a quien administra el servidor de Sofibot**

- [ ] Id. de inquilino e id. de cliente.
- [ ] El valor del secreto, por un canal seguro (gestor de contraseñas), **nunca por correo**.
- [ ] La lista de **valores** de los roles de datos.

---

# Parte C · Inicio de sesión e informes con IA (sistemas)

## Paso C1 · Configurar `.env`

```bash
cd /opt/sofibot
nano .env
```

```ini
SOFIBOT_AUTH=entra
SOFIBOT_PUBLIC_URL=https://informes.empresa.local
ENTRA_TENANT_ID=<Id. de directorio (inquilino)>
ENTRA_CLIENT_ID=<Id. de aplicación (cliente)>
ENTRA_CLIENT_SECRET=<valor del secreto>
# Funcionalidad 1: la API de informes con la cuenta de cada autor.
SOFIBOT_CODE_API=entra
```

`SOFIBOT_PUBLIC_URL` debe coincidir con la URI de redirección del paso B1, sin `/auth/callback`.
Si la salida a internet pasa por un proxy: `HTTPS_PROXY=http://<proxy>:<puerto>`.

## Paso C2 · Arrancar y entrar

```bash
docker compose up -d
docker compose logs sofibot --tail 20
```

✅ **Bien si** el log dice `Portal sign-in: entra`, y al abrir
`https://informes.empresa.local`:

1. sale la portada con **Iniciar sesión con Microsoft**;
2. tras entrar, la página **Explorar** muestra tu nombre arriba;
3. con `Sofibot.Admin`, el menú tiene **Administración**.

❌ **Si no**:
- `RuntimeError: SOFIBOT_AUTH=entra needs ...` en el log → falta una variable del paso C1.
- Microsoft muestra un código `AADSTS…` → tabla de [problemas frecuentes](#problemas-frecuentes).

Todavía no verás informes: falta decir qué tablas ve cada rol (parte E).

---

# Parte D · Consultas de datos (DBA, sistemas y Datasofi)

La funcionalidad 2 corre en su propio contenedor, con su propia configuración y su propio
login de SQL Server. Detalle: [11 · Consultas de datos](11-consultas.md).

## Paso D1 · Segundo login de solo lectura (lo hace el DBA)

El DBA ejecuta otra vez `sql/crear-login-lectura.sql`, cambiando arriba
`@login = N'sofibot_consultas'` y con **otra** contraseña. Te pasa la contraseña por un canal seguro.

## Paso D2 · Configuración propia: `.env.consultas`

```bash
cd /opt/sofibot
cp .env.consultas.example .env.consultas
chmod 600 .env.consultas
nano .env.consultas
```

Rellena: `SQLSERVER_HOST`, `SQLSERVER_PORT`, `SQLSERVER_DATABASE` (los mismos que en `.env`),
`SQLSERVER_PASSWORD` (la del paso D1), y `ENTRA_TENANT_ID` y `ENTRA_CLIENT_ID` (los mismos
que en `.env`; aquí no va el secreto). Deja `SOFIBOT_QUERY_ENABLED=1`.

## Paso D3 · El catálogo: `reports/catalogo.json`

Dice qué se puede preguntar a cada tabla: medidas (ventas, margen…) y dimensiones (mes,
tienda…). **Datasofi lo prepara** a partir del esquema de vuestras tablas (sin ver datos) y
lo revisa con alguien que conozca los datos. Una vez copiado en `reports/`, comprobarlo:

```bash
docker compose run --rm sofibot sofibot catalog
```

✅ **Bien si** lista las tablas con sus medidas y dimensiones y no muestra `ERROR`.

## Paso D4 · Activar el servicio

```bash
mkdir -p consultas
nano .env
```

En `.env`, cambia `COMPOSE_PROFILES` y añade la dirección interna del servicio:

```ini
COMPOSE_PROFILES=https,consultas
SOFIBOT_QUERY_URL=http://consultas:8080
```

```bash
docker compose up -d
docker compose ps
```

✅ **Bien si** `docker compose ps` muestra `consultas` en estado `running (healthy)` y, en el
portal, **Administración → Funcionalidad 2** dice *Servicio de consultas: Responde* y el
catálogo sin problemas.

❌ **Si no**: `docker compose logs consultas --tail 30`. Si dice `Permission denied` en
`/app/consultas`, la carpeta `consultas/` no es del mismo usuario que `reports/`
(`SOFIBOT_UID` en `.env`): `sudo chown $(id -u):$(id -g) consultas`.

Para que la página **Consultas** funcione, cada persona debe **cerrar sesión y volver a
entrar** una vez después de este paso.

---

# Parte E · Permisos y usuarios (administrador de Sofibot)

## Paso E1 · Qué tablas ve cada rol

En el portal, con `Sofibot.Admin`: **Administración → Permisos**.

- Una fila por rol de datos: escribe su **valor** exacto en "Nuevo rol" y marca sus tablas
  Gold (o *Todas*). Guardar. Repetir con cada rol.
- La última columna muestra qué informes verá cada rol.

Los cambios se aplican al momento, sin reiniciar, y quedan registrados con tu correo.

✅ **Bien si** una persona con un rol de datos entra y ve en **Informes** solo los informes
de sus tablas.

## Paso E2 · Comprobar la parte técnica

En **Administración**:

- [ ] *SQL Server*: **Comprobar la conexión** → correcta y *Login de solo lectura: Sí*.
- [ ] *Contrato de esquema*: si falta o está antiguo, **Actualizar el contrato de esquema**.
- [ ] *Entra ID*: *Claves públicas de Entra ID: Accesibles*.
- [ ] *Funcionalidad 1*: *API de informes: entra*.
- [ ] *Funcionalidad 2*: *Servicio de consultas: Responde*.

## Paso E3 · Conectar Claude o Codex (cada persona, una vez)

Para autores (`Sofibot.Autor`) y para quien consulte con su IA (`Sofibot.Consultas`).
Cada persona necesita tener instalada su IA (Claude Desktop, Claude Code o Codex; la
página **Conectar tu IA** enlaza a sus instalaciones). Después, en esa página:

1. **Descargar el conector de Sofibot** (`sofibot-conectar.zip`) y extraerlo.
2. Doble clic en `sofibot-mcp.exe`. Si Windows avisa (SmartScreen): *Más información →
   Ejecutar de todas formas*.
3. El conector explica lo que va a hacer (con **D** se ve el detalle), pide iniciar sesión
   con Microsoft, comprueba los roles y configura solo las IAs que encuentre, guardando
   una copia de cada fichero que cambia.
4. Cerrar y volver a abrir la IA.

No hace falta Python ni permisos de administrador. La página también tiene la configuración
manual, con dónde está el fichero de cada IA, para quien la prefiera.

Si el certificado del portal es de la autoridad de Caddy o de una CA interna, añadid a la
configuración del conector `SOFIBOT_CA_BUNDLE` con la ruta del certificado de esa autoridad
en el PC.

> Los datos que consulta la IA llegan a su proveedor. Usad solo las cuentas de IA que la
> empresa haya autorizado ([06 · Seguridad](06-seguridad.md)).

---

## Comprobación final

| Prueba | Resultado esperado |
|---|---|
| Entrar con una persona sin ningún rol | Microsoft no la deja pasar (`AADSTS50105`) |
| Entrar con un rol de datos | Ve solo los informes de sus tablas |
| Consultas → una consulta sencilla | Tabla con resultados; en *Administración* no aparece ningún valor |
| Autor: pedir a Claude un informe | Aparece el borrador en **Revisión** |
| Revisor: vista previa y publicar | El informe aparece en **Informes** para quien tenga sus tablas |
| Un revisor intenta publicar su propio borrador | Lo impide: debe publicarlo otro revisor |
| Claude con el conector de consultas: «¿cuánto vendimos el mes pasado?» | Responde citando tabla, medidas y periodo |

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `AADSTS50011` (redirect URI mismatch) | La URI del paso B1 no coincide con `SOFIBOT_PUBLIC_URL` + `/auth/callback` |
| `AADSTS50105` | La persona no tiene ningún rol asignado (paso B7) |
| `AADSTS65001` o `AADSTS90094` (se necesita aprobación) | Falta el consentimiento de administrador (paso B6) |
| `AADSTS7000215` / `invalid_client` en el log | Secreto incorrecto o caducado: nuevo secreto y cambiar `ENTRA_CLIENT_SECRET` |
| Consultas: «Tu sesión para consultas ha caducado» | Normal cada hora, o tras activar el servicio: **Volver a entrar** |
| Consultas: «no está activado» | Falta `SOFIBOT_QUERY_URL` en `.env` (paso D4) |
| Consultas: «No tienes tablas consultables» | Sus roles de datos no tienen tablas del catálogo (pasos D3 y E1) |
| El conector de Claude dice `Audience doesn't match` | El ámbito del paso B4 no es `api://<id. de cliente>/access_as_user` |
| El conector de Claude dice `certificate verify failed` | Falta `SOFIBOT_CA_BUNDLE` (paso E3) |
| Las APIs responden 403 `does not have the Sofibot.… role` | Falta ese rol en Entra (paso B7); después, volver a iniciar sesión |

Más casos: [09 · Entra ID](09-inicio-sesion-entra.md#problemas-frecuentes),
[11 · Consultas](11-consultas.md) y [Solución de problemas](solucion-de-problemas.md).

## Chuleta de comandos

| Comando | Qué hace |
|---|---|
| `docker compose ps` | Estado de los contenedores (`sofibot`, `consultas`, `proxy`) |
| `docker compose logs sofibot --tail 50` | Últimos mensajes del portal |
| `docker compose logs consultas --tail 50` | Últimos mensajes del servicio de consultas |
| `docker compose up -d` | Aplicar cambios de `.env` o `.env.consultas` |
| `docker compose run --rm sofibot sofibot catalog` | Comprobar el catálogo de consultas |
| `docker compose run --rm sofibot sofibot drafts` | Borradores de informes y su estado |
| `docker compose run --rm consultas sofibot consultas-registro consultas --out /app/consultas/consultas.csv` | Exportar el registro de consultas (sin valores) |

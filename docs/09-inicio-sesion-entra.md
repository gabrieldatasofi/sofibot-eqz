# 09 · Inicio de sesión con Microsoft Entra ID

Cada persona entra en el portal con su cuenta de la empresa (la misma de Outlook o Teams) y
**solo ve los informes construidos con tablas Gold a las que tiene acceso**.

El reparto es sencillo: **Entra ID solo valida el inicio de sesión** (dice quién es la
persona) y **Sofibot decide qué puede hacer** (sus roles y sus tablas).

```
 Usuario ──▶ portal Sofibot ──▶ inicio de sesión de Microsoft ──▶ vuelve al portal: "es ana@empresa.com"
                                (contraseña, MFA, acceso condicional:
                                 lo que tenga configurado la empresa)

 En Sofibot, carpeta acceso/:
 Usuarios y roles               Tablas Gold por rol de datos       Informes (report.json)
 (acceso/usuarios.json)         (acceso/permisos.json)
 ──────────────────────────     ───────────────────────────        ────────────────────────────────
 ana@  ── Direccion,            Direccion  "*"  (todas)            ventas-tiendas  lee gold.ventas_mes_tienda
          Sofibot.Admin         Ventas     gold.ventas_mes_tienda, margen-producto lee gold.ventas_mes_producto
 luis@ ── Ventas,                          gold.ventas_mes_producto                y gold.costes_producto
          Sofibot.Consultas
```

En el ejemplo, Luis (*Ventas*) ve `ventas-tiendas` pero no `margen-producto`, porque no
tiene `gold.costes_producto`. Ana (*Direccion*) ve los dos.

- **Quién puede iniciar sesión** lo valida Entra ID. Opcionalmente, sistemas puede limitarlo
  a un grupo de personas (paso 4).
- **Qué roles tiene cada persona** se decide en Sofibot: **Administración → Usuarios**
  (fichero `acceso/usuarios.json`). Hay dos tipos de roles:
  - **roles de funcionalidad** (`Sofibot.Autor`, `Sofibot.Revisor`, `Sofibot.Consultas`,
    `Sofibot.Admin`), qué puede hacer ([ver abajo](#roles-de-las-funcionalidades));
  - **roles de datos** (nombres que decidís vosotros: `Direccion`, `Ventas`…), qué tablas ve.
- **Qué tablas Gold da cada rol de datos** se decide en **Administración → Permisos por
  tabla** (fichero `acceso/permisos.json`).
- **Qué tablas usa cada informe** lo declara el propio informe (en su `report.json`), y
  Sofibot comprueba al generarlo que no lee ninguna otra.
- Una persona ve un informe si sus roles, juntos, le dan acceso a **todas** las tablas de
  ese informe. Los informes se generan por adelantado y son iguales para todos los que los
  ven: no se puede mostrar solo una parte de un informe.
- Quien inicia sesión pero no está en `acceso/usuarios.json` entra al portal y no ve nada.
- Los cambios de usuarios y permisos se aplican al momento, sin reiniciar y sin que la
  persona tenga que volver a iniciar sesión.
- Sofibot no guarda contraseñas de los usuarios ni tiene acceso a su correo ni a otros
  datos de Microsoft 365. Solo recibe su nombre y su correo.

Reparto del trabajo:

| Quién | Qué | Sección |
|---|---|---|
| Sistemas (administrador de Entra ID) | Registrar la aplicación y, si se quiere, limitar quién puede entrar | 1 a 5 |
| Quien administra el servidor de Sofibot | Configurar `.env` y nombrar al primer administrador | 6 a 8 |
| Administradores de Sofibot (`Sofibot.Admin`) | Usuarios, roles y permisos por tabla, desde el portal | 9 |

**Requisito previo:** el portal ya se abre por HTTPS con su nombre definitivo, por ejemplo
`https://informes.empresa.local`. Ver [08 · Acceso desde la red con HTTPS](08-acceso-https.md).
Entra ID no admite otra cosa.

---

## Parte 1 · En Entra ID (sistemas)

Se hace en el [Centro de administración de Microsoft Entra](https://entra.microsoft.com)
con un usuario con rol *Administrador de aplicaciones* (o superior). **No hay que crear
roles de aplicación**: los roles se gestionan en Sofibot.

### 1. Registrar la aplicación

**Identidad → Aplicaciones → Registros de aplicaciones → Nuevo registro**:

| Campo | Valor |
|---|---|
| Nombre | `Sofibot Informes` (es el que verán los usuarios) |
| Tipos de cuenta compatibles | **Solo las cuentas de este directorio organizativo** (inquilino único) |
| URI de redirección | Plataforma **Web**, `https://informes.empresa.local/auth/callback` (con vuestro nombre) |

Pulsar **Registrar**. En **Información general**, anotar:

- **Id. de aplicación (cliente)**
- **Id. de directorio (inquilino)**

### 2. Crear el secreto de cliente

**Certificados y secretos → Secretos de cliente → Nuevo secreto de cliente**:

- Descripción: `Servidor Sofibot`. Caducidad: 12 meses (o la que marque vuestra política).
- Copiar el **Valor** en ese momento: después no vuelve a mostrarse. Es el *Valor*, no el
  *Id. de secreto*.
- **Anotar la fecha de caducidad en un calendario.** Cuando caduque, nadie podrá entrar
  hasta que se cree uno nuevo y se cambie en Sofibot (ver "Operación").

### 3. Exponer la API (para los asistentes de IA y las consultas)

Las funcionalidades de Sofibot reciben un token de Microsoft del usuario. Para que el
conector de la IA (o la página Consultas del portal) pueda pedirlo, en el mismo registro:

1. **Exponer una API → Agregar** el URI de id. de aplicación (`api://<id. de cliente>`,
   el que propone) y **Agregar un ámbito**: nombre `access_as_user`, quién puede dar
   consentimiento *Administradores y usuarios*, con un nombre y una descripción
   (*Usar Sofibot en tu nombre*).
2. **Autenticación → Agregar una plataforma → Aplicaciones móviles y de escritorio**, con
   la URI de redirección `http://localhost`, y en **Configuración avanzada**,
   **Permitir flujos de clientes públicos: Sí**. Es lo que usa el conector de la IA para
   abrir el inicio de sesión en el navegador de la persona.
3. **Permisos de API → Agregar un permiso → Mis API → Sofibot Informes → access_as_user**
   y **Conceder consentimiento de administrador**, para que nadie tenga que aceptarlo.

Si solo se van a ver informes en el portal, este paso se puede dejar para más adelante.

### 4. Opcional: limitar quién puede iniciar sesión

Sin este paso, cualquier persona del directorio puede iniciar sesión, pero no ve nada
hasta que un administrador de Sofibot le da roles. Para que Entra ID ni siquiera deje
entrar a quien no debe:

**Identidad → Aplicaciones → Aplicaciones empresariales → Sofibot Informes**:

1. **Propiedades → ¿Se requiere asignación?: Sí → Guardar.**
2. **Usuarios y grupos → Agregar usuario o grupo**: elegir las personas o, mejor, un grupo
   (por ejemplo *Usuarios Sofibot*). Sin elegir rol: aparece "Acceso predeterminado".

Las personas que no están asignadas ven un aviso de Microsoft y no llegan al portal.
Asignar grupos requiere Microsoft Entra ID P1 (incluido en Microsoft 365 E3/E5 y Business
Premium).

### 5. Consentimiento y entrega de los datos

- Sofibot solo pide los permisos básicos de inicio de sesión (`openid`, `profile`). Si
  en vuestra organización los usuarios no pueden dar su consentimiento a aplicaciones:
  **Permisos de API → Conceder consentimiento de administrador**.
- Entregar a quien administra el servidor de Sofibot los tres datos: **Id. de inquilino**,
  **Id. de cliente** y **valor del secreto**. Enviar el secreto por un canal seguro (gestor
  de contraseñas), **no por correo**.

---

## Parte 2 · En el servidor de Sofibot

### 6. Configurar `.env`

```ini
SOFIBOT_AUTH=entra
SOFIBOT_PUBLIC_URL=https://informes.empresa.local
ENTRA_TENANT_ID=<Id. de directorio (inquilino)>
ENTRA_CLIENT_ID=<Id. de aplicación (cliente)>
ENTRA_CLIENT_SECRET=<valor del secreto>
# Horas que dura la sesión antes de volver a pasar por Microsoft (por defecto 8)
SOFIBOT_SESSION_HOURS=8
```

`SOFIBOT_PUBLIC_URL` debe coincidir exactamente con la URI de redirección del paso 1, sin
`/auth/callback`.

El servidor debe poder conectarse a internet por HTTPS con `login.microsoftonline.com`. Si
la salida a internet pasa por un proxy de la empresa, añadir en `.env`
`HTTPS_PROXY=http://proxy.empresa.local:8080`. La hora del servidor debe estar sincronizada
(NTP).

### 7. Nombrar al primer administrador

Al principio nadie tiene roles, así que nadie puede abrir la administración. El primer
administrador se nombra una sola vez desde el servidor, con su **correo de Microsoft** (el
que usa para iniciar sesión):

```bash
docker compose run --rm sofibot sofibot users add ana@empresa.com Sofibot.Admin
```

A partir de ahí, Ana da los roles al resto desde el portal (paso 9). El mismo comando sin
argumentos (`sofibot users`) lista quién tiene qué roles.

### 8. Arrancar y probar

```bash
docker compose up -d
docker compose logs sofibot | grep "sign-in"     # debe decir: Portal sign-in: entra
```

Abrir `https://informes.empresa.local`. Debe redirigir al inicio de sesión de Microsoft y
volver al portal, con el nombre del usuario y "Cerrar sesión" arriba a la derecha. El
administrador ve **Administración** en el menú.

Si falta algún valor en `.env`, el portal no arranca y `docker compose logs sofibot`
indica cuál falta.

---

## Parte 3 · En el portal (administradores de Sofibot)

### 9. Roles de datos, permisos por tabla y usuarios

En este orden, desde **Administración**:

1. **Permisos por tabla**: crear los roles de datos (los nombres los decidís vosotros, sin
   espacios ni acentos: `Direccion`, `Ventas`, `Tiendas`…) y marcar las tablas Gold de cada
   uno. La columna *Informes que ve* muestra el efecto.
2. **Usuarios**: añadir a cada persona por su correo de Microsoft y marcar sus roles de
   funcionalidad y de datos. La columna *Tablas que ve* muestra el resultado.
3. Comprobar con una persona de cada perfil que ve sus informes y no los demás.

Perfiles típicos:

| Perfil | Roles |
|---|---|
| Solo ve informes | un rol de datos (`Ventas`) |
| Consulta datos con su IA | `Sofibot.Consultas` + rol de datos |
| Escribe informes con su IA | `Sofibot.Autor` + rol de datos |
| Revisa y publica informes | `Sofibot.Revisor` + rol de datos |
| Administra Sofibot | `Sofibot.Admin` (+ rol de datos si también ve informes) |

Ficheros de la carpeta `acceso/` (los escribe la administración; se pueden editar a mano):

```json
// acceso/usuarios.json: roles de cada persona, por correo (mayúsculas indiferentes)
{
  "usuarios": {
    "ana@empresa.com": ["Direccion", "Sofibot.Admin"],
    "luis@empresa.com": ["Sofibot.Consultas", "Ventas"]
  }
}
```

```json
// acceso/permisos.json: tablas Gold de cada rol de datos
{
  "roles": {
    "Direccion": ["*"],
    "Ventas": ["gold.ventas_mes_tienda", "gold.ventas_mes_producto"],
    "Costes": ["gold.costes_producto"]
  }
}
```

- En `permisos.json`, cada rol tiene la lista de tablas Gold que puede ver, con su nombre en
  `reports/gold_schema.json`. `"*"` = todas. Los nombres de rol distinguen mayúsculas.
- Una persona con varios roles suma las tablas de todos ellos. En el ejemplo, alguien con
  *Ventas* y *Costes* ve también los informes que cruzan ventas y costes.
- **Lo que no está en la lista no se ve.** Un informe que usa una tabla que no tiene ningún
  rol solo lo ven los roles con `"*"`.
- Un informe nuevo sobre tablas ya permitidas lo ven automáticamente los roles que tienen
  esas tablas: no hay que tocar nada.
- Cada cambio desde el portal queda registrado (quién y cuándo, en **Administración →
  Cambios de administración**) y el fichero anterior se guarda en `acceso/.copias/`.
- `acceso/usuarios.json` contiene correos de personas: tratadlo como dato personal (no lo
  enviéis por correo ni a asistentes de IA).

Comprobar los permisos por tabla:

```bash
docker compose run --rm sofibot sofibot permissions
```

Muestra, para cada rol, sus tablas y los informes que ve. También avisa de las tablas que no
existen en el esquema Gold y de los informes que no podría ver ningún rol.

**Instalaciones anteriores.** Antes de esta versión los permisos estaban en
`reports/permisos.json` y los roles en Entra ID. Sofibot sigue leyendo
`reports/permisos.json` hasta que se guardan los permisos desde el portal, que los pasa a
`acceso/permisos.json`. Los roles de aplicación que queden en Entra ID se ignoran: hay que
dar los roles a cada persona en **Usuarios** y después se pueden borrar de Entra ID.

---

## Roles de las funcionalidades

Los roles de datos deciden **qué tablas** puede tocar cada persona. Para usar las
funcionalidades de Sofibot además de ver informes, cada una tiene su propio rol, que se da
en **Administración → Usuarios** como los demás (y nunca va en `permisos.json`):

| Rol | Para |
|---|---|
| `Sofibot.Autor` | Escribir informes con un asistente de IA ([10 · API de informes](10-api-informes.md)) |
| `Sofibot.Revisor` | Revisar, previsualizar y publicar esos informes en `/revision` |
| `Sofibot.Consultas` | Consultar datos ([11 · Consultas](11-consultas.md)) |
| `Sofibot.Admin` | Página `/admin`: estado técnico, usuarios, permisos y documentación |

Cada persona sigue necesitando sus roles de datos: un autor solo ve el esquema de sus
tablas, un revisor solo los borradores de sus tablas y quien consulta, solo sus tablas.

Las APIs de las funcionalidades reciben un token de Microsoft del usuario (paso 3) en lugar
de la sesión del portal. Sofibot comprueba en cada llamada que el token es de este
inquilino, para esta aplicación, de un usuario (no de una aplicación) y que no ha caducado,
y busca los roles de ese correo en `acceso/usuarios.json`. No necesita el secreto para eso.
El servicio de consultas lee la misma carpeta `acceso/`, en solo lectura.

Con el servicio de consultas activo (`SOFIBOT_QUERY_URL`), el portal pide también ese ámbito
al iniciar sesión, para que su página **Consultas** pueda preguntar en nombre del usuario.
El token se guarda en la memoria del portal, no en la cookie, y caduca a la hora: entonces
la página pide volver a entrar (sin contraseña si la sesión de Microsoft sigue abierta).

---

## Operación

| Tarea | Dónde |
|---|---|
| Dar acceso a una persona | Administración → Usuarios: añadir su correo y sus roles. Si se exige asignación (paso 4), añadirla también al grupo en Entra ID |
| Quitar el acceso | Administración → Usuarios → quitar. Se aplica al momento, también a su sesión abierta y a su IA |
| Nuevo perfil de acceso | Administración → Permisos por tabla: nuevo rol de datos con sus tablas; después darlo en Usuarios |
| Informe nuevo | Nada, si sus tablas ya están en algún rol. Comprobar con `sofibot permissions` quién lo ve |
| Tabla Gold nueva | Añadirla a los roles que deben verla en Permisos por tabla |
| Primer administrador, o recuperar el acceso si nadie es administrador | `docker compose run --rm sofibot sofibot users add <correo> Sofibot.Admin` |
| Renovar el secreto (antes de que caduque) | Entra ID → Certificados y secretos → nuevo secreto; cambiar `ENTRA_CLIENT_SECRET` en `.env`; `docker compose up -d`; borrar el secreto antiguo en Entra ID |
| Ver quién entra | `docker compose logs sofibot \| grep "Signed in"`: cada inicio de sesión queda registrado con el correo y los roles |

Un administrador no puede quitarse a sí mismo el rol `Sofibot.Admin` desde el portal: lo
hace otro administrador (o el comando `sofibot users remove <correo> Sofibot.Admin`).

La API de administración (`/api/admin/...`) sigue usando `SOFIBOT_ADMIN_TOKEN`, no Entra ID.
Las APIs de las funcionalidades (`/api/code`, `/api/query`) usan Entra ID: ver
[Roles de las funcionalidades](#roles-de-las-funcionalidades).

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| Microsoft muestra `AADSTS50011` (redirect URI mismatch) | La URI de redirección del paso 1 no coincide con `SOFIBOT_PUBLIC_URL` + `/auth/callback` (revisar `https`, el nombre y que no sobre una `/` al final) |
| Microsoft muestra `AADSTS50105` | Se exige asignación (paso 4) y la persona no está asignada (ni su grupo) |
| Microsoft muestra `AADSTS65001` o pide consentimiento | Conceder el consentimiento de administrador (pasos 3 y 5) |
| "No se ha podido iniciar sesión" y en el log `invalid_client` / `AADSTS7000215` / `AADSTS7000222` | Secreto incorrecto o caducado: crear uno nuevo y cambiar `ENTRA_CLIENT_SECRET` |
| "Inicio de sesión no disponible" | El servidor no llega a `login.microsoftonline.com`: firewall de salida o falta `HTTPS_PROXY`. Detalle en `docker compose logs sofibot` |
| Entra, pero "No tienes acceso a ningún informe" | No está en Usuarios, su correo no coincide con el de Microsoft, su rol de datos no tiene tablas en Permisos o un fichero de `acceso/` tiene un error (el log lo dice; `sofibot users` y `sofibot permissions`) |
| "Sin acceso a este informe" | Sus roles no incluyen alguna de las tablas del informe (ver `tables` en su `report.json`) |
| Nadie puede abrir Administración | Nadie tiene `Sofibot.Admin`: `sofibot users add <correo> Sofibot.Admin` en el servidor |
| Las APIs responden 401 `Invalid token: Audience doesn't match` | El cliente pide el token para otra aplicación: el ámbito debe ser `api://<id. de cliente de Sofibot>/access_as_user` |
| Las APIs responden 403 `does not have the Sofibot.… role` | Falta darle a la persona el rol de esa funcionalidad en Administración → Usuarios |
| Pide iniciar sesión otra vez tras reiniciar Sofibot | Normal: las sesiones se cierran al reiniciar. Con Microsoft ya iniciado, vuelve a entrar sin escribir la contraseña |

# 09 · Inicio de sesión con Microsoft Entra ID

Cada persona entra en el portal con su cuenta de la empresa (la misma de Outlook o Teams) y
**solo ve los informes construidos con tablas Gold a las que tiene acceso**.

Cómo funciona:

```
 Usuario ──▶ portal Sofibot ──▶ inicio de sesión de Microsoft ──▶ vuelve al portal con sus roles
                                (contraseña, MFA, acceso condicional:
                                 lo que tenga configurado la empresa)

 Roles (en Entra ID)        Tablas Gold por rol               Informes (report.json)
                            (reports/permisos.json)
 ───────────────────        ───────────────────────────       ────────────────────────────────
 Direccion ── Ana, Luis     "*"  (todas)                      ventas-tiendas  lee gold.ventas_mes_tienda
 Ventas    ── grupo Ventas  gold.ventas_mes_tienda,           margen-producto lee gold.ventas_mes_producto
                            gold.ventas_mes_producto                          y gold.costes_producto
```

En el ejemplo, *Ventas* ve `ventas-tiendas` pero no `margen-producto`, porque no tiene
`gold.costes_producto`. *Dirección* ve los dos.

- **Quién tiene cada rol** se decide en Entra ID: lo gestiona sistemas, como cualquier
  otra aplicación de la empresa.
- **Qué tablas Gold ve cada rol** se decide en Sofibot, en el fichero `reports/permisos.json`.
- **Qué tablas usa cada informe** lo declara el propio informe (en su `report.json`), y
  Sofibot comprueba al generarlo que no lee ninguna otra.
- Una persona ve un informe si sus roles, juntos, le dan acceso a **todas** las tablas de
  ese informe. Los informes se generan por adelantado y son iguales para todos los que los
  ven: no se puede mostrar solo una parte de un informe.
- Sofibot no guarda contraseñas de los usuarios ni tiene acceso a su correo ni a otros
  datos de Microsoft 365. Solo recibe su nombre, su correo y sus roles.

Reparto del trabajo:

| Quién | Qué | Sección |
|---|---|---|
| Sistemas (administrador de Entra ID) | Registrar la aplicación, crear los roles y asignarlos | 1 a 5 |
| Quien administra el servidor de Sofibot | Configurar `.env` y `reports/permisos.json` | 6 a 8 |

**Requisito previo:** el portal ya se abre por HTTPS con su nombre definitivo, por ejemplo
`https://informes.empresa.local`. Ver [08 · Acceso desde la red con HTTPS](08-acceso-https.md).
Entra ID no admite otra cosa.

---

## Parte 1 · En Entra ID (sistemas)

Se hace en el [Centro de administración de Microsoft Entra](https://entra.microsoft.com)
con un usuario con rol *Administrador de aplicaciones* (o superior).

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

### 3. Crear los roles

**Roles de aplicación → Crear rol de aplicación**, uno por cada perfil de acceso:

| Campo | Ejemplo |
|---|---|
| Nombre para mostrar | `Dirección` |
| Tipos de miembros permitidos | **Usuarios o grupos** |
| Valor | `Direccion` (sin espacios ni acentos; es el que se usa en `permisos.json`) |
| Descripción | `Ve todos los informes` |
| ¿Quiere habilitar este rol de aplicación? | Sí |

Los nombres de los roles los decidís vosotros. Por ejemplo `Direccion`, `Ventas`,
`Tiendas` o `Finanzas`. Pasad la lista de **valores** a quien administra Sofibot.

### 4. Exigir asignación y asignar los roles

**Identidad → Aplicaciones → Aplicaciones empresariales → Sofibot Informes**:

1. **Propiedades → ¿Se requiere asignación?: Sí → Guardar.** Así solo entran las personas
   con un rol asignado. Las demás ven un aviso de Microsoft y no llegan al portal.
2. **Usuarios y grupos → Agregar usuario o grupo**: elegir las personas (o un grupo) y el
   rol. Repetir para cada rol.

Asignar **grupos** en lugar de personas facilita el mantenimiento: quien entra en el grupo
*Ventas* recibe el rol automáticamente. Requiere Microsoft Entra ID P1, incluido en
Microsoft 365 E3/E5 y Business Premium.

### 5. Consentimiento y entrega de los datos

- Sofibot solo pide los permisos básicos de inicio de sesión (`openid`, `profile`). Si
  en vuestra organización los usuarios no pueden dar su consentimiento a aplicaciones:
  **Permisos de API → Conceder consentimiento de administrador**.
- Entregar a quien administra el servidor de Sofibot los tres datos: **Id. de inquilino**,
  **Id. de cliente** y **valor del secreto**, más la lista de roles. Enviar el secreto por
  un canal seguro (gestor de contraseñas), **no por correo**.

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

### 7. Decidir qué tablas ve cada rol: `reports/permisos.json`

```json
{
  "roles": {
    "Direccion": ["*"],
    "Ventas": ["gold.ventas_mes_tienda", "gold.ventas_mes_producto"],
    "Costes": ["gold.costes_producto"]
  }
}
```

- Las claves son los **valores** de los roles del paso 3. Se distinguen mayúsculas y
  minúsculas.
- Cada rol tiene la lista de tablas Gold que puede ver, con su nombre en
  `reports/gold_schema.json`. `"*"` = todas.
- Una persona con varios roles suma las tablas de todos ellos. En el ejemplo, alguien con
  *Ventas* y *Costes* ve también los informes que cruzan ventas y costes.
- **Lo que no está en la lista no se ve.** Un informe que usa una tabla que no tiene ningún
  rol solo lo ven los roles con `"*"`.
- Un informe nuevo sobre tablas ya permitidas lo ven automáticamente los roles que tienen
  esas tablas: no hay que tocar este fichero.
- Los cambios se aplican al momento, sin reiniciar.

Comprobar el fichero:

```bash
docker compose run --rm sofibot sofibot permissions
```

Muestra, para cada rol, sus tablas y los informes que ve. También avisa de las tablas que no
existen en el esquema Gold y de los informes que no podría ver ningún rol.

### 8. Arrancar y probar

```bash
docker compose up -d
docker compose logs sofibot | grep "sign-in"     # debe decir: Portal sign-in: entra
```

Abrir `https://informes.empresa.local`. Debe redirigir al inicio de sesión de Microsoft y
volver al portal, con el nombre del usuario y "Cerrar sesión" arriba a la derecha.
Comprobar con una persona de cada rol que ve sus informes y no los demás.

Si falta algún valor en `.env`, el portal no arranca y `docker compose logs sofibot`
indica cuál falta.

---

## Roles de las funcionalidades

Los roles de los pasos 3 y 7 deciden **qué tablas** puede tocar cada persona. Para usar las
funcionalidades de Sofibot además de ver informes, cada una tiene su propio rol, que se
crea igual que en el paso 3 y se asigna igual que en el paso 4 (y nunca va en `permisos.json`):

| Valor | Nombre para mostrar | Para |
|---|---|---|
| `Sofibot.Autor` | Autor de informes | Escribir informes con un asistente de IA ([10 · API de informes](10-api-informes.md)) |
| `Sofibot.Revisor` | Revisor de informes | Revisar, previsualizar y publicar esos informes en `/revision` |
| `Sofibot.Consultas` | Consultas de datos | Consultar datos ([11 · Consultas](11-consultas.md)) |
| `Sofibot.Admin` | Administración de Sofibot | Página `/admin`: estado técnico, permisos de usuarios y documentación |

Cada persona sigue necesitando sus roles de tablas: un autor solo ve el esquema de sus
tablas, un revisor solo los borradores de sus tablas y quien consulta, solo sus tablas.

Las dos APIs reciben un token de Microsoft del usuario en lugar de la sesión del portal.
Para que un cliente (el servidor MCP de los autores o el futuro agente de consultas) pueda
pedirlo, en el mismo registro de aplicación:

1. **Exponer una API → Agregar** el URI de id. de aplicación (`api://<id. de cliente>`,
   el que propone) y **Agregar un ámbito**: nombre `access_as_user`, quién puede dar
   consentimiento *Administradores y usuarios*, con un nombre y una descripción
   (*Usar Sofibot en tu nombre*).
2. **Autenticación → Agregar una plataforma → Aplicaciones móviles y de escritorio**, con
   la URI de redirección `http://localhost`, y en **Configuración avanzada**,
   **Permitir flujos de clientes públicos: Sí**. Es lo que usa el servidor MCP del autor
   para abrir el inicio de sesión en su navegador.
3. **Permisos de API → Agregar un permiso → Mis API → Sofibot Informes → access_as_user**
   y **Conceder consentimiento de administrador**, para que nadie tenga que aceptarlo.

Sofibot comprueba en cada llamada que el token es de este inquilino, para esta aplicación,
de un usuario (no de una aplicación) y que no ha caducado. No necesita el secreto para eso.

Con el servicio de consultas activo (`SOFIBOT_QUERY_URL`), el portal pide también ese ámbito
al iniciar sesión, para que su página **Consultas** pueda preguntar en nombre del usuario.
El token se guarda en la memoria del portal, no en la cookie, y caduca a la hora: entonces
la página pide volver a entrar (sin contraseña si la sesión de Microsoft sigue abierta).

Los permisos de tablas (`permisos.json`) se pueden editar también desde **Administración →
Permisos**, con el rol `Sofibot.Admin`.

---

## Operación

| Tarea | Dónde |
|---|---|
| Dar acceso a una persona | Entra ID → Aplicaciones empresariales → Sofibot Informes → Usuarios y grupos (o añadirla al grupo) |
| Quitar el acceso | Quitar la asignación en Entra ID. Su sesión abierta dura como máximo `SOFIBOT_SESSION_HOURS`; para cortarla al momento, `docker compose restart sofibot` (cierra la sesión de todos, que vuelven a entrar solos) |
| Nuevo perfil de acceso | Crear el rol en Entra ID (paso 3), asignarlo y añadir sus tablas a `permisos.json` |
| Informe nuevo | Nada, si sus tablas ya están en algún rol. Comprobar con `sofibot permissions` quién lo ve |
| Tabla Gold nueva | Añadirla a los roles que deben verla en `permisos.json` |
| Renovar el secreto (antes de que caduque) | Entra ID → Certificados y secretos → nuevo secreto; cambiar `ENTRA_CLIENT_SECRET` en `.env`; `docker compose up -d`; borrar el secreto antiguo en Entra ID |
| Ver quién entra | `docker compose logs sofibot \| grep "Signed in"`: cada inicio de sesión queda registrado con el correo y los roles |

La API de administración (`/api/admin/...`) sigue usando `SOFIBOT_ADMIN_TOKEN`, no Entra ID.
Las APIs de las funcionalidades (`/api/code`, `/api/query`) usan Entra ID: ver
[Roles de las funcionalidades](#roles-de-las-funcionalidades).

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| Microsoft muestra `AADSTS50011` (redirect URI mismatch) | La URI de redirección del paso 1 no coincide con `SOFIBOT_PUBLIC_URL` + `/auth/callback` (revisar `https`, el nombre y que no sobre una `/` al final) |
| Microsoft muestra `AADSTS50105` | La persona no tiene ningún rol asignado (paso 4) |
| Microsoft muestra `AADSTS65001` o pide consentimiento | Conceder el consentimiento de administrador (paso 5) |
| "No se ha podido iniciar sesión" y en el log `invalid_client` / `AADSTS7000215` / `AADSTS7000222` | Secreto incorrecto o caducado: crear uno nuevo y cambiar `ENTRA_CLIENT_SECRET` |
| "Inicio de sesión no disponible" | El servidor no llega a `login.microsoftonline.com`: firewall de salida o falta `HTTPS_PROXY`. Detalle en `docker compose logs sofibot` |
| Entra, pero "No tienes acceso a ningún informe" | Su rol no está en `permisos.json`, el valor no coincide (mayúsculas) o el fichero tiene un error: `sofibot permissions` |
| "Sin acceso a este informe" | Sus roles no incluyen alguna de las tablas del informe (ver `tables` en su `report.json`) |
| Las APIs responden 401 `Invalid token: Audience doesn't match` | El cliente pide el token para otra aplicación: el ámbito debe ser `api://<id. de cliente de Sofibot>/access_as_user` |
| Las APIs responden 403 `does not have the Sofibot.… role` | Falta asignar a la persona el rol de esa funcionalidad (o lo acaba de recibir: que vuelva a iniciar sesión) |
| Pide iniciar sesión otra vez tras reiniciar Sofibot | Normal: las sesiones se cierran al reiniciar. Con Microsoft ya iniciado, vuelve a entrar sin escribir la contraseña |

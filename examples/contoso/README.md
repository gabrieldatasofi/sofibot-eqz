# Ejemplo: Contoso

Datos públicos de ejemplo (ContosoRetailDW de Microsoft o Contoso V2 de SQLBI) para probar Sofibot sin datos reales.

| Fichero | Qué hace |
|---|---|
| `01-crear-gold.sql` | Crea `gold.month_store` y `gold.month_product` a partir de la base Contoso restaurada |
| `reports/contoso-ventas-tiendas/` | Informe interactivo: barra de filtros, KPIs, gráficos y tablas que se recalculan, Excel por elemento y Excel completo |
| `reports/contoso-productos-excel/` | Informe que solo entrega un Excel con varias hojas |
| `compose.yaml` | Portal de pruebas Contoso, separado del proyecto (puerto 8085), con proxy HTTPS opcional |
| `.env.example` | Plantilla de su configuración (`examples/contoso/.env`) |
| `preparar.ps1` | Deja el entorno de pruebas listo en un paso: configuración, login, capa gold, portal e informes |
| `refrescar.ps1` | Pipeline de prueba: recrea la capa gold y pide al portal de pruebas que regenere los informes |
| `activar-entra.ps1` | Activa Entra ID y las dos funcionalidades completas en el `.env` de pruebas, sin mostrar el secreto |
| `reports/catalogo.json` | Catálogo de consultas de Contoso (funcionalidad 2) |

La base Contoso no se incluye: es una base pública de ejemplo que hay que restaurar en un
SQL Server de pruebas.

## Entorno de pruebas (Datasofi)

El entorno Contoso tiene su propia configuración, informes y salida. No usa el `.env`, la
carpeta `reports/` ni `output/` del proyecto, que quedan para la instalación del cliente.
Usa el mismo código (`src/`), así que sirve para probar cualquier cambio de Sofibot.

Requisitos: Docker Desktop, `sqlcmd` y la base Contoso restaurada en el SQL Server local
(tu usuario de Windows debe ser administrador de ese SQL Server). Después, desde la raíz:

```powershell
.\examples\contoso\preparar.ps1                       # base ContosoRetailDW en localhost
.\examples\contoso\preparar.ps1 -Database ContosoV2 -Server 'localhost\SQLEXPRESS'
```

El script crea `examples/contoso/.env` con contraseña y token generados (no los muestra),
crea o actualiza el login `sofibot_lectura` con esa contraseña, crea la capa gold si falta,
arranca el portal de pruebas, construye todos los informes y abre el navegador. Si el
`.env` ya existe lo reutiliza, así que se puede ejecutar siempre que cambie el código.

A mano, cuando solo cambia el código:

```powershell
docker compose -f examples/contoso/compose.yaml up -d --build
docker compose -f examples/contoso/compose.yaml run --rm sofibot sofibot build --all
```

Portal: http://localhost:8085/dashboard. Los informes se leen directamente de
`examples/contoso/reports/` y la salida va a `examples/contoso/output/` (fuera de git).

## Probar el inicio de sesión con Entra ID (Datasofi)

Se prueba con el Entra ID de Datasofi y dos o más usuarios de Datasofi, en local:
`http://localhost` es la única dirección sin HTTPS que Entra ID admite, así que no hace
falta el proxy HTTPS. Son los mismos pasos que hará el cliente
([09 · Inicio de sesión con Entra ID](../../docs/09-inicio-sesion-entra.md)), con estos valores.

**1. En Entra ID de Datasofi** (pasos 1, 2 y 4 de la guía; sin roles de aplicación):

- Registro de aplicación `Sofibot pruebas`, inquilino único, URI de redirección **Web**
  `http://localhost:8085/auth/callback`.
- Un secreto de cliente (caducidad corta, por ejemplo 3 meses).
- Opcional: en Aplicaciones empresariales → `Sofibot pruebas`, "¿Se requiere asignación?" = Sí
  y asignar los usuarios de prueba (sin rol), para comprobar que los demás no entran.

**2. En `examples/contoso/.env`** añade (el secreto no sale de ese fichero):

```ini
SOFIBOT_AUTH=entra
SOFIBOT_PUBLIC_URL=http://localhost:8085
ENTRA_TENANT_ID=<Id. de directorio (inquilino)>
ENTRA_CLIENT_ID=<Id. de aplicación (cliente)>
ENTRA_CLIENT_SECRET=<valor del secreto>
```

**3. Permisos y usuarios.** El entorno de Contoso usa la carpeta `acceso/` de la **raíz del
proyecto**, la misma que con cualquier otra base: usuarios y roles (`usuarios.json`),
permisos por tabla (`permisos.json`) y cuentas locales como `sofibot.admin`
(`cuentas-locales.json`). Ninguno va en git. Si `acceso/permisos.json` no existe, créalo con
los roles de datos de Contoso (o desde **Administración → Permisos por tabla**; el formato
general está en `acceso/permisos.example.json`):

```json
{
  "roles": {
    "Direccion": ["*"],
    "Tiendas": ["gold.month_store"],
    "Producto": ["gold.month_product"]
  }
}
```

| Rol | Tablas Gold | Ve |
|---|---|---|
| `Direccion` | todas | los dos informes |
| `Tiendas` | `gold.month_store` | Contoso · Ventas por tienda |
| `Producto` | `gold.month_product` | Contoso · Productos (Excel) |

Si pruebas con otra base, cambia solo los permisos por tabla: usuarios y cuentas locales
siguen siendo los mismos.

Los roles de cada persona los da Sofibot. Tú serás el administrador (con tu correo de
Microsoft); a la otra persona le das `Tiendas` desde **Administración → Usuarios**:

```powershell
docker compose -f examples/contoso/compose.yaml run --rm sofibot sofibot users add <tu correo> Sofibot.Admin Direccion
```

**4. Reconstruir, regenerar y probar:**

```powershell
docker compose -f examples/contoso/compose.yaml up -d --build
docker compose -f examples/contoso/compose.yaml run --rm sofibot sofibot permissions
docker compose -f examples/contoso/compose.yaml run --rm sofibot sofibot build --all
```

Abre http://localhost:8085 y entra con cada usuario. Para tener dos sesiones a la vez, usa
una ventana de incógnito para el segundo.

Qué comprobar:

- [ ] Redirige al inicio de sesión de Microsoft y vuelve al portal con tu nombre arriba.
- [ ] `Direccion` ve los dos informes; `Tiendas` solo el de tiendas.
- [ ] Con `Tiendas`, abrir a mano `http://localhost:8085/output/contoso-productos-excel/` muestra "Sin acceso a este informe".
- [ ] Un usuario de Datasofi que no está en Usuarios entra pero no ve ningún informe (con asignación exigida, Microsoft no le deja pasar: `AADSTS50105`).
- [ ] Al darle `Tiendas` en Administración → Usuarios, ve el informe de tiendas al recargar, sin volver a iniciar sesión.
- [ ] "Cerrar sesión" vuelve a pedir el inicio de sesión.
- [ ] Al quitar `gold.month_store` de `Tiendas` en Administración → Permisos por tabla, el informe desaparece sin reiniciar.
- [ ] `docker compose -f examples/contoso/compose.yaml logs sofibot` muestra un `Signed in:` por cada entrada.

Para volver al portal sin inicio de sesión, quita `SOFIBOT_AUTH=entra` de `.env` y ejecuta
`docker compose -f examples/contoso/compose.yaml up -d`.

## Probar Sofibot completo: informes con IA, revisión, consultas y administración

Sobre la misma aplicación `Sofibot pruebas` del apartado anterior.

**1. En Entra ID**, en esa aplicación ([09 · Roles de las funcionalidades](../../docs/09-inicio-sesion-entra.md#roles-de-las-funcionalidades)):

- Nada de roles: en **Administración → Usuarios** date `Sofibot.Autor`, `Sofibot.Revisor` y
  `Sofibot.Consultas` (además de `Sofibot.Admin` y `Direccion`).
- **Exponer una API**: URI `api://<id. de cliente>` y ámbito `access_as_user`.
- **Autenticación → Aplicaciones móviles y de escritorio**: `http://localhost`, y
  *Permitir flujos de clientes públicos: Sí*.
- **Permisos de API → Mis API → access_as_user** y conceder el consentimiento de administrador.

**2. Configuración y arranque**, desde la raíz:

```powershell
.\examples\contoso\activar-entra.ps1
```

Pide el id. de inquilino, el id. de aplicación y el secreto (no se muestra), los escribe en
`examples/contoso/.env` con el resto de opciones (API de informes con Entra ID, servicio de
consultas en el puerto 8086) y arranca el entorno.

**3. Qué comprobar**, en http://localhost:8085:

- [ ] Portada → Iniciar sesión con Microsoft → Explorar, con las dos tarjetas activas.
- [ ] Consultas: ventas por país de 2024 en el formulario.
- [ ] Administración: comprobar la conexión, usuarios y permisos (cambiar uno y ver el efecto) y documentación.
- [ ] Conectar tu IA: descargar los conectores, configurarlos en Claude Code y preguntar
      por los datos de Contoso; después pedirle un informe nuevo.
- [ ] Revisión: generar la vista previa del borrador de Claude y publicarlo.
- [ ] Registros: `examples/contoso/consultas/registro.sqlite` (consultas) y
      `examples/contoso/reports/.borradores/registro.sqlite` (informes).

## Probar desde otro equipo de la red (como en el cliente)

Tu PC hace de **servidor de Sofibot** y otro ordenador de la misma red hace de **PC de un
empleado**. Es el montaje del cliente completo: HTTPS
([08 · Acceso desde la red con HTTPS](../../docs/08-acceso-https.md)) + Entra ID + permisos por tabla.

```
Otro ordenador ──(red de la oficina)──▶ tu PC: proxy HTTPS (443) ──▶ Sofibot de pruebas
```

Haz antes la prueba en local de la sección anterior: así, si algo falla aquí, es de la red
o del certificado.

**1. Nombre de tu PC.** En tu PC, `ipconfig` → "Dirección IPv4", por ejemplo `192.168.1.50`.
El nombre será esa IP con guiones y `.nip.io`: `192-168-1-50.nip.io` (DNS público
que devuelve la IP escrita en el nombre; hace de DNS interno del cliente). Compruébalo desde
el otro ordenador:

```powershell
Resolve-DnsName 192-168-1-50.nip.io      # debe devolver 192.168.1.50
```

Si no la devuelve (algunos routers bloquean estas respuestas), usa el fichero `hosts` del
otro ordenador: como administrador, añade a `C:\Windows\System32\drivers\etc\hosts` la línea
`192.168.1.50 192-168-1-50.nip.io`.

**2. Entra ID.** En el registro `Sofibot pruebas` → Autenticación → añadir la URI de
redirección Web `https://192-168-1-50.nip.io/auth/callback`.

**3. `examples/contoso/.env`.** Añade o cambia:

```ini
COMPOSE_PROFILES=https
SOFIBOT_DOMAIN=192-168-1-50.nip.io
SOFIBOT_TLS=internal
SOFIBOT_PUBLIC_URL=https://192-168-1-50.nip.io
```

**4. Firewall de Windows de tu PC.** En PowerShell como administrador:

```powershell
New-NetFirewallRule -DisplayName "Sofibot pruebas HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow -Profile Private
Get-NetConnectionProfile      # la red debe ser "Private"; si es "Public", cambiarla en Configuración de Windows
```

**5. Arrancar** (en tu PC):

```powershell
docker compose -f examples/contoso/compose.yaml up -d --build
docker compose -f examples/contoso/compose.yaml ps      # "sofibot" healthy y "proxy" running
```

**6. Certificado** (lo que haría sistemas del cliente con GPO o Intune). En tu PC, extrae el
certificado raíz de Caddy:

```powershell
docker compose -f examples/contoso/compose.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt .\sofibot-raiz.crt
```

Cópialo al otro ordenador (USB, carpeta compartida) e instálalo allí para tu usuario, sin
permisos de administrador (Windows pide confirmación):

```powershell
Import-Certificate -FilePath .\sofibot-raiz.crt -CertStoreLocation Cert:\CurrentUser\Root
```

Usa Edge o Chrome, que usan los certificados de Windows. Firefox tiene su propio almacén.

**7. Probar.** En el otro ordenador abre `https://192-168-1-50.nip.io`:

- [ ] Sin aviso de certificado, con el candado.
- [ ] Inicio de sesión de Microsoft y vuelta al portal con el nombre del usuario.
- [ ] Las mismas comprobaciones de permisos de la sección anterior.
- [ ] Sin el paso 6 (o desde otro equipo sin el certificado), el navegador muestra
  "La conexión no es privada": es lo que verían los empleados si sistemas no reparte el
  certificado.

**Al terminar:**

```powershell
# En el otro ordenador: quitar el certificado de pruebas
Get-ChildItem Cert:\CurrentUser\Root | Where-Object Subject -like "*Caddy Local Authority*" | Remove-Item
# En tu PC (administrador): quitar la regla del firewall
Remove-NetFirewallRule -DisplayName "Sofibot pruebas HTTPS"
```

Y en `examples/contoso/.env` quita `COMPOSE_PROFILES=https` y vuelve a
`SOFIBOT_PUBLIC_URL=http://localhost:8085`. Si la IP de tu PC cambia (DHCP), hay que
repetir los pasos 1 a 3 con la nueva.

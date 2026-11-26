# 10 · Funcionalidad 1: crear informes con IA por API

Un asistente de IA (Claude, Codex, Copilot…) puede escribir informes **sin acceso a la
carpeta del servidor** y **sin ver datos**: lee el esquema de las tablas Gold, escribe un
borrador del informe y lo envía a revisión. Una persona con el rol de revisor lo ve en una
vista previa y lo publica, o lo rechaza con un comentario.

```
 Autor + su asistente de IA                 Revisor (persona)                  Portal
 (rol Sofibot.Autor)                        (rol Sofibot.Revisor)
   lee el esquema de SUS tablas  ─┐
   escribe el borrador            ├─▶ /api/code ─▶ borrador ─▶ /revision: código,
   lo comprueba y lo envía       ─┘   (sin datos)    enviado     vista previa ─▶ publicar ─▶ informe
```

- La API **no devuelve datos** ni acepta SQL, y lo que escribe **no se ejecuta**.
- Cada persona entra con su cuenta de Microsoft: Sofibot sabe **quién** escribió, envió,
  previsualizó y publicó cada informe, y lo guarda en un registro.
- El autor solo ve el esquema de **sus** tablas (las de sus roles en `acceso/permisos.json`)
  y solo puede escribir informes sobre ellas. El revisor solo ve los borradores de sus tablas.

Es la funcionalidad 1 de Sofibot. La funcionalidad 2, consultar datos, es un camino
separado: ver [11 · Consultas de datos](11-consultas.md).

## Roles

Se dan a cada persona en **Administración → Usuarios** ([09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md#roles-de-las-funcionalidades)):

| Rol (valor) | Qué permite |
|---|---|
| `Sofibot.Autor` | Usar la API de informes: esquema y borradores de sus tablas |
| `Sofibot.Revisor` | Página `/revision` del portal: vista previa, publicar o rechazar |

Además, cada persona necesita uno o varios **roles de datos** (con sus tablas en `acceso/permisos.json`), como
para ver informes. Un revisor no puede publicar un borrador que haya enviado él mismo
(salvo con `SOFIBOT_REVIEW_OWN=1`).

## Activarla

En `.env`:

```ini
SOFIBOT_AUTH=entra          # el portal con Entra ID (necesario para la página de revisión)
SOFIBOT_CODE_API=entra      # la API de informes con la cuenta de cada autor
```

`SOFIBOT_CODE_API=off` (por defecto) la desactiva. `SOFIBOT_CODE_API=token` usa un token
compartido (`SOFIBOT_API_TOKEN`) **solo para pruebas**: no se sabe qué persona hizo cada
cosa, no se filtra por tablas y el registro pone "token compartido".

## Rutas

Todas con la cabecera `Authorization: Bearer <token de Entra ID del autor>`. El servidor
MCP (abajo) lo obtiene solo.

| Método y ruta | Qué hace |
|---|---|
| `GET /api/code/schema` | Esquema de las tablas del autor (columnas, tipos, descripciones) y `report_guide`, la guía para escribir informes. Lee `reports/gold_schema.json`, no la base de datos |
| `GET /api/code/reports` | Informes publicados sobre sus tablas: nombre, descripción y tablas |
| `GET /api/code/drafts` | Borradores sobre sus tablas, con su estado |
| `POST /api/code/drafts` | Crear un borrador: `{"slug", "name", "table", "description"}` desde la plantilla, o `{"slug", "from_report": true}` como copia de un informe publicado |
| `GET /api/code/drafts/<slug>` | Estado, historial (quién hizo qué) y, si se rechazó, el comentario |
| `GET /api/code/drafts/<slug>/files/<fichero>` | Leer `report.json` o un `.py` |
| `PUT /api/code/drafts/<slug>/files/<fichero>` | Escribirlo: `{"content": "..."}` |
| `POST /api/code/drafts/<slug>/check` | Comprobación estática (abajo) |
| `POST /api/code/drafts/<slug>/submit` | Comprobar y enviar a revisión |
| `DELETE /api/code/drafts/<slug>` | Borrar el borrador (no afecta al informe publicado) |

Estados: `draft` (en edición) → `submitted` (enviado) → `published` (publicado) o
`rejected` (rechazado, con comentario). Cualquier cambio en un fichero lo devuelve a
`draft` y descarta su vista previa: lo que se publica es siempre lo que se revisó.

**La comprobación** (`check` y `submit`) revisa, sin ejecutar el código ni abrir la base de
datos, que `report.json` es válido, que los `.py` no tienen errores de sintaxis y que las
tablas Gold del código están en `tables`, en `gold_schema.json` y entre las del autor. No
puede saber si las consultas funcionan: eso se ve en la vista previa.

## Revisar y publicar: `/revision`

Las personas con el rol `Sofibot.Revisor` ven el enlace **Revisión** en el portal:

1. Lista de borradores sobre sus tablas, los enviados primero.
2. En cada uno: el código, el historial y los botones:
   - **Generar vista previa**: ejecuta el borrador contra la base de datos, como un build,
     en una carpeta que solo ven los revisores. **Abrir vista previa** la muestra.
   - **Publicar**: copia el código a `reports/<informe>/` y, si hay vista previa, la pasa
     al portal en ese momento. Sin vista previa, el informe aparece tras el siguiente build.
   - **Rechazar**, con un comentario que el autor ve en su asistente.

Si el informe ya existía, su código anterior se guarda en
`reports/.borradores/.anteriores/<informe>-<fecha>/`.

Sin Entra ID, lo mismo en el servidor (queda registrado como "línea de comandos del servidor"):

```bash
docker compose run --rm sofibot sofibot drafts                    # borradores y su estado
docker compose run --rm sofibot sofibot publish <informe>         # publicar (después: sofibot build)
docker compose run --rm sofibot sofibot reject <informe> --comment "Usa meses completos"
```

Y por la API de administración (`SOFIBOT_ADMIN_TOKEN`, [05 · Operación](05-operacion.md)):
`GET /api/admin/drafts`, `GET /api/admin/drafts/<slug>/files/<fichero>`,
`POST /api/admin/drafts/<slug>/publish` y `POST /api/admin/drafts/<slug>/reject`.

## Registro: quién hizo qué

Cada operación queda en `reports/.borradores/registro.sqlite` (tabla `eventos`: fecha,
persona, operación, informe, detalle): crear, escribir, enviar, vista previa, publicar,
rechazar y borrar. El historial de un borrador se ve en `/revision/<informe>` y en
`GET /api/code/drafts/<slug>`. El log del portal también lo anota (`Report code API: ...`).

## Conectar el asistente de IA (MCP)

`mcp-server/sofibot_informes_mcp.py` presenta la API como herramientas MCP (`describe_schema`,
`list_reports`, `list_drafts`, `create_draft`, `read_file`, `write_file`, `check_draft`,
`submit_draft`, `draft_status`, `delete_draft`) para Claude Code, Claude Desktop, Codex u
otros clientes. Se instala en el equipo del autor, no en el servidor. La forma más sencilla
es la página **Conectar tu IA** del portal: descarga `sofibot-conectar.zip` con
`sofibot-mcp.exe` (los dos conectores en un programa de Windows, sin Python). Con doble clic,
el programa inicia sesión, comprueba los roles y configura Claude Desktop, Claude Code y
Codex él solo; la página también da la configuración manual. Datasofi genera el `.exe` con
`mcp-server/build-exe.ps1` antes de construir la imagen. Con Python, a mano:

```bash
python -m venv .venv-mcp
.venv-mcp/bin/pip install -r mcp-server/requirements.txt        # Windows: .venv-mcp\Scripts\pip
```

Configuración para Claude Code (`.mcp.json` en la carpeta donde se trabaja; en Windows,
`"command": ".venv-mcp/Scripts/python.exe"`):

```json
{
  "mcpServers": {
    "sofibot": {
      "type": "stdio",
      "command": ".venv-mcp/bin/python",
      "args": ["mcp-server/sofibot_informes_mcp.py"],
      "env": {
        "SOFIBOT_URL": "https://informes.empresa.local",
        "SOFIBOT_ENTRA_TENANT_ID": "<Id. de directorio (inquilino)>",
        "SOFIBOT_ENTRA_CLIENT_ID": "<Id. de aplicación (cliente) de Sofibot>"
      }
    }
  }
}
```

La primera vez que el asistente usa una herramienta se abre el navegador para iniciar
sesión con Microsoft. La sesión se guarda en `~/.sofibot/msal-cache.json` (solo en ese
equipo) y las siguientes llamadas no piden nada. Si el portal usa un certificado de una
CA interna: `"SOFIBOT_CA_BUNDLE": "<ruta al certificado de la CA>"`.

Después basta con pedir el informe: *"crea un informe de ventas por tienda de los últimos
12 meses, con Excel"*. El asistente sigue la guía que devuelve `describe_schema` y envía
el borrador cuando se lo pidáis.

## Seguridad

- La IA trabaja **solo con la estructura** de las tablas del autor: ninguna ruta devuelve
  filas, totales, recuentos ni resultados ([06 · Seguridad](06-seguridad.md)).
- El código no se ejecuta hasta que un revisor genera la vista previa. La vista previa
  tiene datos reales y solo la ven revisores con permiso sobre esas tablas; nunca vuelve a
  la IA.
- La API no tiene credenciales de SQL Server: solo el build y la vista previa usan el login
  de solo lectura.

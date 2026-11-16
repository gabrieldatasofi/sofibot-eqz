# 12 · Arquitectura técnica de Sofibot

Visión de conjunto para quien administra o mantiene Sofibot. El detalle de cada parte está
en los documentos enlazados.

## Qué es

Sofibot se conecta en **solo lectura** a las tablas **Gold** de un SQL Server y ofrece dos
funcionalidades separadas:

| | 1 · Informes | 2 · Consultas |
|---|---|---|
| Para qué | Informes web y Excel cuidados y repetibles | Preguntas al momento: medidas por dimensiones |
| Con IA | El asistente del autor escribe el código **sin ver datos** | La IA del usuario (Claude, Codex) consulta **con sus permisos** y ve los resultados |
| Quién decide qué se publica o se ve | Un revisor publica cada informe; cada persona ve los informes de sus tablas | Los permisos del usuario, en cada consulta |
| Documentación | [10 · API de informes](10-api-informes.md) | [11 · Consultas](11-consultas.md) |

Lo único que comparten es **el inicio de sesión** (Microsoft Entra ID) y **los permisos
por tabla** (`reports/permisos.json`).

## Piezas

```
                      Microsoft Entra ID (cuentas, MFA, roles)
                                   │
 Navegador ──HTTPS──▶ Caddy (proxy) ─┬─▶ sofibot      portal, informes, funcionalidad 1, administración
                                     └─▶ consultas    funcionalidad 2 (/api/query)
 Claude / Codex ──MCP local──▶ (mismo HTTPS, con el token de Microsoft del usuario)
                                   │
 sofibot   ── login sofibot_lectura    (solo lectura) ──▶ SQL Server, esquema gold
 consultas ── login sofibot_consultas  (solo lectura) ──▶ SQL Server, esquema gold
```

| Contenedor | Proceso | Configuración | Escribe en |
|---|---|---|---|
| `sofibot` | `sofibot serve` (`server.py`) | `.env` | `output/` (informes generados), `reports/` (permisos, borradores, registros) |
| `consultas` (perfil `consultas`) | `sofibot serve-consultas` (`consultas/server.py`) | `.env.consultas` | `consultas/` (su registro). Lee `reports/` en solo lectura |
| `proxy` (perfil `https`) | Caddy | `caddy/Caddyfile` | certificados |

## Pantallas del portal

| Ruta | Quién | Qué |
|---|---|---|
| `/` | Todos | Portada con *Iniciar sesión con Microsoft* |
| `/explore` | Con sesión | Las dos funcionalidades, según los roles |
| `/informes` | Con sesión | Informes publicados que puede ver (los suyos marcados) y sus borradores |
| `/consultas` | Rol `Sofibot.Consultas` | Formulario de consultas. El portal no consulta la base: reenvía la petición al servicio de consultas con el token del propio usuario |
| `/conectar` | Con sesión | Configuración de Claude y Codex y descarga de los conectores MCP |
| `/revision` | Rol `Sofibot.Revisor` | Código, vista previa, publicar o rechazar borradores |
| `/admin` | Rol `Sofibot.Admin` | Estado (SQL Server, esquema, Entra ID, funcionalidades, MCP), permisos y esta documentación |
| `/output/<informe>/` | Con permiso sobre sus tablas | El informe generado y su Excel |

## Identidad y permisos

- **Portal**: inicio de sesión con Entra ID (OpenID Connect con PKCE, `auth.py`). La
  sesión es una cookie firmada con nombre, correo y roles.
- **APIs** (`/api/code`, `/api/query`): un token de acceso de Entra ID del usuario
  (`identity.py`): de este inquilino, para esta aplicación, de una persona y sin caducar.
- **Roles de funcionalidad** (en Entra ID): `Sofibot.Autor`, `Sofibot.Revisor`,
  `Sofibot.Consultas`, `Sofibot.Admin`.
- **Roles de tablas** (en Entra ID, con sus tablas en `reports/permisos.json`, editable en
  `/admin/permisos`): qué tablas Gold puede tocar cada persona en las dos funcionalidades.

Detalle: [09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md).

## Funcionalidad 1: crear informes

```
 Autor + Claude/Codex ──MCP informes──▶ /api/code ──▶ reports/.borradores/<informe>/  (no se ejecuta)
                                                            │ enviar
 Revisor ──/revision──▶ vista previa (build real, solo revisores) ──▶ publicar ──▶ reports/<informe>/ + output/<informe>/
```

- La IA recibe el esquema de las tablas del autor y la guía `report_guide.md`; nunca datos.
- Un informe es `report.json` (nombre y tablas Gold que lee) más `generate.py` (consultas y
  contenido, con `Report` y `Workbook`). Ver [04 · Crear informes](04-crear-informes.md).
- El build ejecuta `generate.py` en su propio proceso y comprueba que solo lee las tablas
  declaradas. Un build fallido nunca sustituye al informe anterior.
- Registro: `reports/.borradores/registro.sqlite` (quién creó, escribió, envió, previsualizó,
  publicó o rechazó).

## Funcionalidad 2: consultas

```
 Usuario ──/consultas (portal)──┐
 Claude/Codex ──MCP consultas───┴──▶ /api/query ──▶ catálogo ──▶ permisos ──▶ SQL con parámetros ──▶ SQL Server
                                          └──▶ consultas/registro.sqlite (quién, qué, desenlace; nunca valores)
```

- `reports/catalogo.json` define qué medidas y dimensiones tiene cada tabla. La API no
  acepta SQL: construye la consulta con nombres del catálogo y valores como parámetros.
- Límites de filas, de tiempo y de consultas por minuto.
- La IA del usuario registra el desenlace de cada pregunta (`respondida`, `no_disponible`…):
  así se sabe qué falta en las tablas Gold.

## Conectores MCP

Se descargan en `/conectar` y se instalan en el equipo de cada persona (`mcp-server/`):

| Conector | Herramientas | Devuelve datos |
|---|---|---|
| `sofibot_informes_mcp.py` | `describe_schema`, `list_reports`, `list_drafts`, `create_draft`, `read_file`, `write_file`, `check_draft`, `submit_draft`, `draft_status`, `delete_draft` | No |
| `sofibot_consultas_mcp.py` | `describe_catalog`, `run_query`, `record_outcome` | Sí, con los permisos del usuario |

Los dos inician sesión con la cuenta de Microsoft del usuario (`sofibot_entra.py`) y
funcionan con Claude Code, Claude Desktop y Codex. Se distribuyen como un solo programa de
Windows, `sofibot-mcp.exe informes|consultas`; con doble clic (sin argumentos) configura
las IAs del usuario (`sofibot_instalar.py`). Datasofi lo genera con
`mcp-server/build-exe.ps1` en cada versión (va en la imagen, no en git), o como scripts de
Python.

## Carpetas

| Carpeta | Contenido |
|---|---|
| `reports/` | Proyectos de informe, `gold_schema.json`, `catalogo.json`, `permisos.json` |
| `reports/.borradores/` | Borradores de la funcionalidad 1, su registro y el código anterior de cada publicación |
| `reports/.admin/` | Registro de la administración y copias de `permisos.json` |
| `output/` | Informes generados; `output/.previews/` las vistas previas de los revisores |
| `consultas/` | Registro de la funcionalidad 2 |
| `docs/`, `mcp-server/` | Esta documentación y los conectores (también dentro de la imagen) |

## Código (`src/sofibot_eqz/`)

| Módulo | Qué hace |
|---|---|
| `db.py`, `schema.py` | Conexión de solo lectura a SQL Server; contrato de esquema |
| `html.py`, `excel.py`, `dynamic.py`, `formatting.py` | Página del informe y Excel |
| `projects.py` | Proyectos de informe y builds |
| `auth.py`, `identity.py`, `access.py` | Inicio de sesión, tokens y roles, tablas por rol |
| `server.py` | Portal: rutas, API de informes y de administración |
| `ui.py`, `pages.py`, `review.py`, `admin.py` | Pantallas |
| `drafts.py`, `report_guide.md` | Funcionalidad 1: borradores, revisión, registro |
| `consultas/` | Funcionalidad 2: catálogo, consulta, registro y su servicio |
| `cli.py` | Comando `sofibot` |

## Instalación y entrega

Dos formas, según quién instala ([01 · Instalación](01-instalacion.md#dos-formas-de-instalar)):

- **Desarrollo** (hoy): `git clone` + `docker compose build`. El código está en el servidor.
- **Cliente**: `docker compose pull` de una imagen versionada y fijada por huella, que
  Datasofi publica en GitHub Container Registry con `publicar-imagen.ps1` (tras pasar los
  tests dentro de la imagen), con el `.exe` de los conectores dentro. El cliente recibe un
  paquete sin código y solo configura `.env`, `.env.consultas` y `reports/`
  ([00 · Instalación con imagen](00-instalacion-con-imagen.md)).

## Reglas de seguridad clave

- Los logins de SQL Server solo tienen `SELECT` sobre el esquema Gold. Es la garantía
  final: el código no puede escribir aunque quisiera.
- Los asistentes de IA que **programan** Sofibot o **escriben informes** nunca ven datos.
  La IA del usuario en la funcionalidad 2 sí recibe los resultados de sus consultas.
- Ningún registro guarda valores de datos. Los errores de SQL Server se registran solo por
  su tipo.
- Ver [06 · Seguridad](06-seguridad.md).

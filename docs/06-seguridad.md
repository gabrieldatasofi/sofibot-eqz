# 06 · Seguridad

## Qué puede y qué no puede hacer Sofibot

| Puede | No puede |
|---|---|
| Leer las tablas y vistas del esquema Gold | Leer otros esquemas o bases de datos |
| Leer la estructura (catálogo) de ese esquema | Insertar, modificar o borrar datos |
| Escribir los informes generados en `output/` | Crear o modificar tablas, vistas, usuarios o permisos |

La garantía es el **permiso del login** (`GRANT SELECT ON SCHEMA::gold`), no el código de
Sofibot: aunque un informe intentara escribir, SQL Server lo rechazaría. `sofibot check`
avisa si el login configurado tiene más permisos de los necesarios.

Además, Sofibot:

- abre la conexión en modo lectura (`ApplicationIntent=ReadOnly`, que usa una réplica de
  lectura si existe en un grupo de disponibilidad);
- cifra la conexión y comprueba el certificado del servidor (`SQLSERVER_ENCRYPT=yes`);
- limita el tiempo de cada consulta (`SQLSERVER_QUERY_TIMEOUT`);
- usa consultas parametrizadas;
- se ejecuta en Docker con un usuario sin privilegios (no root).

## Credenciales

- La contraseña del login solo está en `.env`, en el servidor de Sofibot. Permisos
  `chmod 600 .env`. No se guarda en git ni en la imagen Docker (`.dockerignore` la excluye).
- `SOFIBOT_ADMIN_TOKEN` y `SOFIBOT_VIEWER_PASSWORD` se generan aleatoriamente y se rotan
  si alguien que los conocía deja de necesitarlos.
- `ENTRA_CLIENT_SECRET` (inicio de sesión con Entra ID) solo está en `.env`, caduca y se
  renueva en Entra ID ([09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md)).

## Usuarios del portal

Con `SOFIBOT_AUTH=entra`:

- cada persona entra con su cuenta de la empresa, con la MFA y el acceso condicional que
  tenga configurados Entra ID;
- solo entran las personas con un rol asignado en la aplicación de Entra ID;
- los permisos se dan por **tabla Gold** (`reports/permisos.json`): cada persona solo ve
  los informes cuyas tablas tiene todas permitidas. Lo que no está permitido no se ve, ni en
  el portal ni por su dirección directa;
- cada informe declara en su `report.json` las tablas que lee, y el build falla si una
  consulta lee otra tabla Gold. Es una comprobación contra errores; la garantía final sigue
  siendo la revisión del código del informe por una persona;
- cada inicio de sesión queda en el log con el correo y los roles.

Un informe se genera una vez y todos los que tienen acceso ven los mismos datos: no se
filtra por usuario dentro de un informe.
- Si el login se ve comprometido: cambiar la contraseña con `sql/crear-login-lectura.sql`
  (es re-ejecutable) y actualizar `.env`.

## Consultas de datos

La funcionalidad 2 ([11 · Consultas](11-consultas.md)) devuelve datos al momento a las
personas con el rol `Sofibot.Consultas`, solo de las tablas de sus roles. Es un camino
separado de los informes: su propio contenedor, su propio fichero de configuración
(`.env.consultas`) y su propio login de SQL Server, también de solo lectura.

- No acepta SQL: solo medidas y dimensiones del catálogo (`reports/catalogo.json`), y
  todos los valores van como parámetros.
- Tiene límites de filas, de tiempo y de consultas por minuto.
- Registra cada consulta y cada pregunta con el usuario, **nunca los valores devueltos**.
- **La IA del usuario sí ve datos.** Con el conector MCP de consultas, la IA que use cada
  persona (Claude o Codex) recibe los resultados de sus consultas, que llegan a su
  proveedor. Usadla solo con la cuenta de IA que la empresa autorice (por ejemplo, un plan
  de empresa sin entrenamiento con vuestros datos) y dad el rol `Sofibot.Consultas` solo a
  quien lo necesite.
- Esto no cambia las reglas de los asistentes de IA que escriben informes o programan
  Sofibot: siguen sin ver datos (`AGENTS.md`).

## Datos

- Los informes generados (`output/`) contienen datos de negocio: el acceso al portal debe
  restringirse (ver [05 · Operación](05-operacion.md), "Inicio de sesión") y, fuera del
  propio servidor, ir cifrado con HTTPS (ver [08 · Acceso desde la red con HTTPS](08-acceso-https.md)).
- Los Excel descargados quedan fuera del control de Sofibot: aplicar vuestra política de
  clasificación de información.
- Los informes solo leen las tablas Gold: no deberían contener datos personales salvo que
  estén en esas tablas. Revisar las tablas Gold con esa perspectiva.

## Asistentes de IA

Si se usan asistentes de IA (Claude Code, Copilot, Codex…) para escribir informes:

- El asistente trabaja **solo con la estructura** (`reports/gold_schema.json`), que no
  contiene datos.
- El asistente **no** recibe credenciales de SQL Server ni ejecuta builds contra los datos
  reales: el build lo lanza una persona, que revisa el resultado.
- No se pegan en el asistente resultados, capturas ni Excel con datos reales.
- Si el asistente trabaja a través de la API de informes ([10 · API](10-api-informes.md)),
  actúa con la cuenta del autor (rol `Sofibot.Autor`): recibe solo el esquema de sus tablas
  y escribe borradores que no se ejecutan. Solo un revisor (rol `Sofibot.Revisor`) los
  ejecuta en una vista previa y los publica, y todo queda registrado con quién lo hizo.

Estas reglas están en `AGENTS.md` y en la skill `.claude/skills/nuevo-informe`, que los
asistentes leen automáticamente. Como control técnico adicional, el proyecto incluye
`.claude/settings.json`, que impide a Claude Code leer `.env`, `output/` y ficheros de datos
y ejecutar `sofibot build`, `sofibot check` o `sqlcmd` (ver
[07 · Informes con IA](07-informes-con-ia.md#reglas-de-seguridad-para-claude-code)).

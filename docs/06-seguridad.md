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
- Si el login se ve comprometido: cambiar la contraseña con `sql/crear-login-lectura.sql`
  (es re-ejecutable) y actualizar `.env`.

## Datos

- Los informes generados (`output/`) contienen datos de negocio: el acceso al portal debe
  restringirse (ver [05 · Operación](05-operacion.md), "Inicio de sesión").
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

Estas reglas están en `AGENTS.md` y en la skill `.claude/skills/nuevo-informe`, que los
asistentes leen automáticamente. Como control técnico adicional, las reglas de permisos
del asistente pueden prohibirle leer `.env` y `output/` y ejecutar `sofibot build`.

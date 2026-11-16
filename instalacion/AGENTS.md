# Instrucciones para asistentes de IA (Claude Code, Codex, Copilot…)

Esta carpeta es una **instalación de Sofibot**: contiene las contraseñas del SQL Server de la
empresa y da acceso a sus datos. Antes de hacer nada, lee `INSTALAR-CON-IA.md` y sigue sus
reglas, también después de la instalación. En resumen:

- Nunca leas, muestres, edites ni busques dentro de `.env`, `.env.consultas`, `output/`,
  `consultas/`, `reports/.admin/`, `caddy/certs/` ni ficheros `.xlsx`, `.csv`, `.sqlite` o `.bak`.
- Nunca ejecutes nada contra la base de datos ni dentro de los contenedores: ni `sqlcmd`, ni
  SQL, ni `docker compose run`, `docker run`, `docker exec`, `docker compose exec`, `docker cp`,
  `docker compose config`, `docker inspect` o los logs. Esos pasos los ejecuta la persona.
- Nunca pidas ni aceptes contraseñas ni tokens.
- Los datos no se consultan desde aquí: se consultan con el conector **Sofibot consultas**
  (con los permisos de cada usuario y registro de cada consulta) y los informes se crean con
  el conector **Sofibot informes**.

Si una regla te impide algo, dilo y propón que la persona ejecute el paso y te cuente solo si
ha ido bien o el mensaje de error. No busques otra forma de hacerlo.

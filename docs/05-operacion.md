# 05 · Operación

## Portal

`docker compose up -d` arranca el portal en `http://localhost:8080`:

| Ruta | Contenido |
|---|---|
| `/dashboard` | Lista de informes con enlace a la página y descarga de los Excel |
| `/output/<slug>/` | Página de un informe |
| `/output/<slug>/<fichero>.xlsx` | Descarga directa de un Excel |
| `/health` | Estado (para monitorización) |

### Inicio de sesión

`SOFIBOT_AUTH` elige cómo se entra al portal:

| Valor | Acceso |
|---|---|
| `entra` | **Recomendado.** Cada persona con su cuenta de Microsoft Entra ID, viendo solo los informes de su rol. Ver [09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md) |
| `basic` | Un usuario (`SOFIBOT_VIEWER_USER`) y una contraseña (`SOFIBOT_VIEWER_PASSWORD`) compartidos. Todos ven todos los informes |
| `none` | Sin inicio de sesión. Solo si nadie más que el administrador llega al portal |

Sin `SOFIBOT_AUTH`: `basic` si `SOFIBOT_VIEWER_PASSWORD` tiene valor y `none` si no.

### Acceso desde la red

Por defecto el portal solo escucha en el propio equipo (`SOFIBOT_BIND=127.0.0.1`). Para
publicarlo:

- **Recomendado**: el proxy HTTPS incluido en `compose.yaml` (Caddy), que se activa con
  `COMPOSE_PROFILES=https` en `.env`. Paso a paso en
  [08 · Acceso desde la red con HTTPS](08-acceso-https.md).
- Si el servidor ya tiene un servidor web (Nginx, IIS…), se puede usar ese como proxy
  inverso hacia `http://127.0.0.1:8080` en lugar del incluido.
- Solo para pruebas en una red interna, sin HTTPS: `SOFIBOT_BIND=0.0.0.0` en `.env` y
  `docker compose up -d`. En ese caso, activar `SOFIBOT_VIEWER_PASSWORD`.

## Pantallas

| Pantalla | Para |
|---|---|
| `/` y `/explore` | Entrar con Microsoft y elegir funcionalidad |
| `/informes` | Ver informes publicados y los borradores propios |
| `/consultas`, `/conectar` | Consultar datos; conectar Claude o Codex |
| `/revision` | Revisores: vista previa y publicación de informes |
| `/admin` | Administradores (`Sofibot.Admin`): estado de SQL Server, esquema, Entra ID, funcionalidades y MCP; **usuarios y roles** (`/admin/usuarios`), **permisos por tabla** (`/admin/permisos`) y **documentación técnica** (`/admin/docs`) |

Desde `/admin` se comprueba la conexión a SQL Server y se actualiza el contrato de esquema
sin usar la línea de comandos. Arquitectura completa: [12 · Arquitectura](12-arquitectura.md).

## Regeneración automática

```ini
SOFIBOT_BUILD_SCHEDULE=06:00            # una vez al día
SOFIBOT_BUILD_SCHEDULE=06:00,14:00      # dos veces al día
TZ=Europe/Madrid
```

El portal regenera todos los informes de `reports/` a esas horas. Conviene programarlo
**después** de la carga diaria del warehouse. Vacío = desactivado.

Alternativa con el programador del sistema (cron), por ejemplo a las 6:30:

```cron
30 6 * * * cd /opt/sofibot && docker compose exec -T sofibot sofibot build --all >> /var/log/sofibot-build.log 2>&1
```

## API de administración

Requiere `SOFIBOT_ADMIN_TOKEN` (mínimo 32 caracteres) en la cabecera `Authorization: Bearer <token>`:

| Método y ruta | Qué hace |
|---|---|
| `GET /api/admin/check` | Prueba la conexión con SQL Server (como `sofibot check`) |
| `POST /api/admin/reports/<slug>/build` | Regenera un informe |
| `POST /api/admin/build-all` | Regenera todos |
| `GET /api/admin/drafts` | Borradores escritos por la API de informes ([10 · API](10-api-informes.md)) |
| `GET /api/admin/drafts/<slug>/files/<fichero>` | Código de un borrador, para revisarlo |
| `POST /api/admin/drafts/<slug>/publish` | Publica un borrador enviado en `reports/` (como `sofibot publish`) |
| `POST /api/admin/drafts/<slug>/reject` | Lo rechaza con `{"comment": "..."}` (como `sofibot reject`) |

```bash
curl -X POST http://localhost:8080/api/admin/build-all -H "Authorization: Bearer $SOFIBOT_ADMIN_TOKEN"
```

Útil para lanzar la regeneración desde el proceso de carga del warehouse (SQL Agent, Data
Factory, Airflow) justo cuando termina.

`GET /api/reports` devuelve la lista de informes generados (con el mismo acceso que el portal).

## Logs

```bash
docker compose logs -f sofibot
```

Cada build registra si ha ido bien y cuánto ha tardado. Si falla, el detalle del error
queda en el log. Los errores de un build no se muestran en el portal ni en la API.

| Registro | Dónde |
|---|---|
| Quién escribió, envió, previsualizó, publicó o rechazó cada informe (funcionalidad 1) | `reports/.borradores/registro.sqlite` y `/revision/<informe>` ([10 · API de informes](10-api-informes.md#registro-quién-hizo-qué)) |
| Consultas de datos y preguntas (funcionalidad 2) | `docker compose logs consultas` y `consultas/registro.sqlite` ([11 · Consultas](11-consultas.md#registro)) |

## Copias de seguridad

| Qué | Cómo |
|---|---|
| `reports/` | Copia de la carpeta, o mejor un repositorio git |
| `.env`, `.env.consultas` | Copia en un gestor de secretos |
| `reports/.borradores/`, `consultas/` | Copia de la carpeta: borradores y registros de quién hizo qué |
| `output/` | No hace falta: `sofibot build --all` lo regenera |

## Parar, reiniciar, desinstalar

```bash
docker compose restart          # reiniciar (tras cambiar .env)
docker compose down             # parar
docker compose down --rmi all   # parar y borrar la imagen
```

El login de SQL Server se elimina con `DROP USER [sofibot_lectura]` en la base y
`DROP LOGIN [sofibot_lectura]` en el servidor.

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

Si `SOFIBOT_VIEWER_PASSWORD` tiene valor, el navegador pide usuario
(`SOFIBOT_VIEWER_USER`) y contraseña para ver el portal. Es un acceso compartido y
sencillo: para usuarios individuales, poner el portal detrás de un proxy con inicio de
sesión corporativo (Microsoft Entra ID, por ejemplo con Azure App Proxy, oauth2-proxy o
Cloudflare Access).

### Acceso desde la red

Por defecto el portal solo escucha en el propio equipo (`SOFIBOT_BIND=127.0.0.1`). Para
publicarlo:

- **Recomendado**: un proxy inverso con HTTPS (Nginx, Caddy, IIS) en el mismo servidor
  que reenvía a `http://127.0.0.1:8080`. Ejemplo con Caddy:

  ```
  informes.equivalenza.com {
      reverse_proxy 127.0.0.1:8080
  }
  ```

- Solo red interna y sin HTTPS: `SOFIBOT_BIND=0.0.0.0` en `.env` y `docker compose up -d`.
  En ese caso, activar `SOFIBOT_VIEWER_PASSWORD`.

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

## Copias de seguridad

| Qué | Cómo |
|---|---|
| `reports/` | Copia de la carpeta, o mejor un repositorio git |
| `.env` | Copia en un gestor de secretos |
| `output/` | No hace falta: `sofibot build --all` lo regenera |

## Parar, reiniciar, desinstalar

```bash
docker compose restart          # reiniciar (tras cambiar .env)
docker compose down             # parar
docker compose down --rmi all   # parar y borrar la imagen
```

El login de SQL Server se elimina con `DROP USER [sofibot_lectura]` en la base y
`DROP LOGIN [sofibot_lectura]` en el servidor.

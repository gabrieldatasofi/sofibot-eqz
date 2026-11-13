# 08 · Acceso desde la red con HTTPS

Por defecto el portal solo responde dentro del propio servidor (`http://localhost:8080`).
Para que lo use el resto de la empresa, Sofibot incluye un **proxy HTTPS** (Caddy) que se
pone delante del portal:

```
 Navegador                                    Servidor de Sofibot
 ─────────                                    ─────────────────────────────────────────
 https://informes.empresa.local  ──443──▶  [ proxy (Caddy) ]  ──▶  [ portal Sofibot :8080 ]
          cifrado con certificado             HTTPS                 solo escucha dentro
```

- El proxy cifra la conexión (HTTPS) y es lo único que se publica en la red.
- El portal sigue escuchando solo dentro del servidor.
- El inicio de sesión con Microsoft Entra ID **exige HTTPS**, así que este paso es previo
  a activarlo.

Hacen falta tres cosas, normalmente a cargo de sistemas: **un nombre**, **un certificado** y
**abrir el puerto 443**.

## 1. Elegir el nombre y darlo de alta en el DNS

Elegir el nombre con el que se abrirá el portal, por ejemplo `informes.empresa.local`, y
crear en el DNS interno un registro **A** que apunte a la IP del servidor de Sofibot.

Comprobar desde un PC de la oficina:

```powershell
Resolve-DnsName informes.empresa.local     # debe devolver la IP del servidor de Sofibot
```

## 2. Elegir el certificado

| Opción | Cuándo | Qué hay que hacer |
|---|---|---|
| **A. Certificado corporativo** (recomendada) | La empresa tiene una autoridad de certificación interna (AD CS) o un certificado comodín (`*.empresa.com`) | Copiar el certificado y su clave al servidor |
| **B. Autoridad propia de Caddy** | No hay certificado corporativo | Repartir una vez el certificado raíz de Caddy a los PCs (GPO o Intune) |
| **C. Let's Encrypt** | Solo si el nombre es un dominio **público** y el servidor es accesible desde internet por el puerto 80 | Nada: Caddy obtiene y renueva el certificado |

Si no se hace nada de esto, el navegador muestra el aviso "La conexión no es privada".

### Opción A · Certificado corporativo

Se necesitan dos ficheros en formato PEM, en la carpeta `caddy/certs/` de Sofibot:

- `cert.pem`: el certificado del nombre elegido **seguido de los certificados intermedios**
  (la cadena completa);
- `key.pem`: la clave privada, sin contraseña.

Si sistemas entrega un fichero `.pfx` / `.p12`, convertirlo en el servidor:

```bash
cd /opt/sofibot
openssl pkcs12 -in certificado.pfx -nokeys -out caddy/certs/cert.pem
openssl pkcs12 -in certificado.pfx -nocerts -nodes -out caddy/certs/key.pem
chmod 600 caddy/certs/key.pem
rm certificado.pfx
```

(Con OpenSSL 3 y un `.pfx` antiguo puede hacer falta añadir `-legacy` a los dos comandos.)

Dónde se guarda y cómo se protege:

- La carpeta `caddy/certs/` está excluida de git: la clave privada no sale del servidor.
- El proxy la lee en solo lectura.
- Cuando el certificado caduque, sustituir los dos ficheros y ejecutar
  `docker compose restart proxy`.

### Opción B · Autoridad propia de Caddy

Caddy crea su propia autoridad de certificación y firma con ella el certificado del
portal. Lo renueva solo. Los PCs confían en él una vez instalado su certificado raíz:

1. Arrancar el proxy (paso 4).
2. Extraer el certificado raíz:

   ```bash
   docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt ./sofibot-raiz.crt
   ```

3. Repartir `sofibot-raiz.crt` a los PCs en **Entidades de certificación raíz de confianza**,
   por GPO (Configuración del equipo → Directivas → Configuración de Windows → Configuración
   de seguridad → Directivas de clave pública) o por Intune (perfil de certificado de
   confianza).

La autoridad se guarda en el volumen Docker `caddy-data`. **No borrarlo**: si se pierde, se
crea otra autoridad y habría que repartir de nuevo el certificado raíz. Por eso
`docker compose down -v` no debe usarse en este servidor.

### Opción C · Let's Encrypt

Solo para un dominio público (por ejemplo `informes.empresa.com`) con el puerto 80 del
servidor accesible desde internet. Poner un correo de contacto en `SOFIBOT_TLS` (paso 3).

## 3. Configurar `.env`

Añadir en el fichero `.env` de Sofibot:

```ini
# Activa el proxy HTTPS
COMPOSE_PROFILES=https
# Nombre del paso 1
SOFIBOT_DOMAIN=informes.empresa.local
# Opción A:
SOFIBOT_TLS="/certs/cert.pem /certs/key.pem"
# Opción B: dejarlo vacío o poner internal
# Opción C: un correo de contacto, por ejemplo SOFIBOT_TLS=sistemas@empresa.com
```

Mantener `SOFIBOT_BIND=127.0.0.1`. El portal no se publica directamente: solo se accede a
través del proxy.

El proxy solo recibe estas dos variables, no las credenciales de SQL Server.

## 4. Arrancar y abrir el puerto

```bash
docker compose up -d
docker compose ps          # deben aparecer "sofibot" (healthy) y "proxy" (running)
```

En el firewall de red que haya entre los PCs y el servidor, permitir el tráfico al servidor
de Sofibot en el puerto **443** y en el **80**. El 80 solo redirige a HTTPS.

Comprobar desde un PC de la oficina:

```powershell
Test-NetConnection informes.empresa.local -Port 443   # TcpTestSucceeded : True
```

Abrir `https://informes.empresa.local` en el navegador: debe mostrar el portal **sin
aviso de certificado**.

## 5. Inicio de sesión

Con HTTPS funcionando ya se puede restringir quién entra:

- **Contraseña compartida**: `SOFIBOT_VIEWER_PASSWORD` en `.env` (ver
  [05 · Operación](05-operacion.md)).
- **Cada persona con su cuenta de la empresa (Microsoft Entra ID)**, viendo solo los
  informes de su rol: [09 · Inicio de sesión con Entra ID](09-inicio-sesion-entra.md).

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| "La conexión no es privada" / `NET::ERR_CERT_AUTHORITY_INVALID` | Opción B sin el certificado raíz instalado en ese PC, o en la opción A falta la cadena intermedia en `cert.pem` |
| `NET::ERR_CERT_COMMON_NAME_INVALID` | El certificado no es del nombre de `SOFIBOT_DOMAIN` |
| `port is already allocated` o `address already in use` al arrancar | Otro programa usa el puerto 80 o el 443 del servidor (otro servidor web, IIS): pararlo o publicar Sofibot a través de ese servidor web |
| `docker compose ps` no muestra `proxy` | Falta `COMPOSE_PROFILES=https` en `.env` |
| `proxy` se reinicia continuamente | `docker compose logs proxy`. Lo habitual: `SOFIBOT_DOMAIN` vacío, o `cert.pem` / `key.pem` que no existen o no se pueden leer |
| `ERR_CONNECTION_TIMED_OUT` desde los PCs | El firewall bloquea el 443, o el DNS apunta a otra IP (`Resolve-DnsName`) |
| `502 Bad Gateway` | El portal no está arrancado: `docker compose ps` y `docker compose logs sofibot` |

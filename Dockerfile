# Sofibot para Equivalenza: portal de informes + comando `sofibot`.
# Debian 12 (bookworm): Microsoft publica para él el ODBC Driver 18 for SQL Server.
# Versiones fijadas: Python (imagen base), driver ODBC (MSODBCSQL_VERSION) y paquetes de
# Python (requirements.txt). Los paquetes de Debian (unixodbc, tzdata, certificados) toman
# la última revisión de seguridad de Debian 12.
FROM python:3.12.16-slim-bookworm

ARG MSODBCSQL_VERSION=18.7.1.1-1
# Vincula la imagen publicada en ghcr.io al repositorio: hereda su visibilidad (privada) y permisos.
LABEL org.opencontainers.image.source="https://github.com/gabrieldatasofi/sofibot-eqz" \
      org.opencontainers.image.title="Sofibot EQZ" \
      org.opencontainers.image.vendor="Datasofi"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc tzdata \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list -o /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18=${MSODBCSQL_VERSION} \
    && apt-get purge -y curl gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 sofibot \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app sofibot

WORKDIR /app
ENV SOFIBOT_HOME=/app \
    TZ=Europe/Madrid \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Primero las dependencias con versiones exactas; después Sofibot sin resolver nada más.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps . && pip check && rm -rf src
# Documentación técnica (página de administración) y conectores MCP que se descargan desde el portal.
COPY docs ./docs
COPY mcp-server ./mcp-server

# reports/: proyectos de informe (código). output/: informes generados. consultas/: registro del
# servicio de consultas (docs/11-consultas.md). Se montan como volúmenes.
RUN mkdir -p /app/reports /app/output /app/consultas && chown sofibot:sofibot /app/reports /app/output /app/consultas
USER sofibot
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]

CMD ["sofibot", "serve", "--host", "0.0.0.0", "--port", "8080"]

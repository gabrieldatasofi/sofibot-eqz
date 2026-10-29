# Sofibot para Equivalenza: portal de informes + comando `sofibot`.
# Debian 12 (bookworm): Microsoft publica para él el ODBC Driver 18 for SQL Server.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc tzdata \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list -o /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y curl gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 sofibot \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app sofibot

WORKDIR /app
ENV SOFIBOT_HOME=/app \
    TZ=Europe/Madrid \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf src

# reports/: proyectos de informe (código). output/: informes generados. Ambos se montan como volúmenes.
RUN mkdir -p /app/reports /app/output && chown sofibot:sofibot /app/reports /app/output
USER sofibot
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]

CMD ["sofibot", "serve", "--host", "0.0.0.0", "--port", "8080"]

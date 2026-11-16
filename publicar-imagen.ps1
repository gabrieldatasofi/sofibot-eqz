<#
  Publica una versión de Sofibot como imagen en GitHub Container Registry y genera el paquete
  de instalación que recibe el cliente (instalación con docker compose pull,
  docs/00-instalacion-con-imagen.md). Lo ejecuta Datasofi en su equipo Windows.

      .\publicar-imagen.ps1              versión de pyproject.toml
      .\publicar-imagen.ps1 -SinSubir    todo menos subir la imagen (para probar)

  Antes, una vez por equipo:  docker login ghcr.io -u <usuario de GitHub>
  (contraseña: un token clásico de GitHub con permiso write:packages).

  Pasos:
    1. Comprueba sofibot-mcp.exe (lo construye con mcp-server\build-exe.ps1 si falta).
    2. Construye la imagen ghcr.io/gabrieldatasofi/sofibot-eqz:<versión> (y :latest).
    3. Pasa los tests dentro de la imagen: si fallan, no se publica nada.
    4. Sube la imagen y anota su huella (sha256).
    5. Genera dist-instalacion\sofibot-eqz-<versión>.tar.gz: compose.yaml que descarga esa
       imagen fijada por su huella (sin código), plantillas .env, Caddyfile, script SQL y docs.
#>
param([string]$Version = '', [switch]$SinSubir)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$registry = 'ghcr.io/gabrieldatasofi/sofibot-eqz'
if (-not $Version) {
    $Version = (Select-String -Path (Join-Path $root 'pyproject.toml') -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
}
$image = "${registry}:$Version"

function Step([string]$text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Check([string]$what) { if ($LASTEXITCODE -ne 0) { throw "$what ha fallado" } }

Step "Sofibot $Version -> $image"
if (git -C $root status --porcelain) {
    Write-Host 'Aviso: hay cambios sin commit; la imagen los incluirá. Mejor publicar desde un commit.' -ForegroundColor Yellow
}

Step '1/5 Conectores para Claude y Codex (sofibot-mcp.exe)'
$exe = Join-Path $root 'mcp-server\dist\sofibot-mcp.exe'
if (-not (Test-Path $exe)) { & (Join-Path $root 'mcp-server\build-exe.ps1') }
& $exe comprobar; Check 'La comprobación de sofibot-mcp.exe'

Step '2/5 Construir la imagen'
docker build --pull -t $image -t "${registry}:latest" $root; Check 'docker build'

Step '3/5 Tests dentro de la imagen'
docker run --rm -u root -v "${root}\tests:/app/tests:ro" $image sh -c `
    'pip install -q pytest==9.2.0 httpx2==2.16.0 2>/dev/null && python -m pytest -q -p no:cacheprovider tests'
Check 'Los tests dentro de la imagen'

$reference = $image
if ($SinSubir) {
    Write-Host '4/5 Sin subir (-SinSubir): el paquete apunta a la etiqueta, sin huella.' -ForegroundColor Yellow
} else {
    Step '4/5 Subir a GitHub Container Registry'
    docker push $image; Check "docker push (¿has hecho 'docker login ghcr.io'?)"
    docker push "${registry}:latest"; Check 'docker push latest'
    $digest = ((docker inspect --format '{{index .RepoDigests 0}}' $image) -split '@')[1]
    $reference = "${image}@$digest"
    Write-Host "Publicada: $reference" -ForegroundColor Green
}

Step '5/5 Paquete de instalación'
$name = "sofibot-eqz-$Version"
$dist = Join-Path $root 'dist-instalacion'
$out = Join-Path $dist $name
Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
foreach ($dir in 'caddy\certs', 'reports', 'output', 'consultas', 'sql', 'docs') { New-Item -ItemType Directory -Force (Join-Path $out $dir) | Out-Null }
foreach ($file in '.env.example', '.env.consultas.example', 'caddy\Caddyfile', 'sql\crear-login-lectura.sql') {
    Copy-Item (Join-Path $root $file) (Join-Path $out $file)
}
Copy-Item (Join-Path $root 'docs\*.md') (Join-Path $out 'docs')
foreach ($keep in 'caddy\certs', 'reports', 'output', 'consultas') { New-Item -ItemType File -Force (Join-Path $out "$keep\.gitkeep") | Out-Null }

# compose.yaml del cliente: el del proyecto sin "build", con la imagen publicada fijada por su huella.
$compose = (Get-Content (Join-Path $root 'compose.yaml') -Raw) -replace '(?m)^\s+build: \.\r?\n', ''
$compose = $compose -replace 'image: datasofi/sofibot-eqz:\S+', "image: $reference"
$header = @"
# Sofibot $Version · instalación con imagen publicada (docs/00-instalacion-con-imagen.md)
#   docker login ghcr.io -u <usuario>        (una vez, con el token de lectura de Datasofi)
#   docker compose pull && docker compose up -d
# No edites este fichero: la configuración va en .env y .env.consultas.
name: sofibot-eqz

"@
$compose = $header + (($compose -split "`n" | Where-Object { $_ -notmatch '^# docker compose (up|run)|^#\s+y, con COMPOSE_PROFILES' }) -join "`n")
[IO.File]::WriteAllText((Join-Path $out 'compose.yaml'), ($compose -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))
Copy-Item (Join-Path $root 'docs\00-instalacion-con-imagen.md') (Join-Path $out 'INSTALAR.md')

$archive = Join-Path $dist "$name.tar.gz"
Remove-Item $archive -ErrorAction SilentlyContinue
tar -czf $archive -C $dist $name; Check 'tar'
Write-Host "`nListo." -ForegroundColor Green
Write-Host "  Imagen:  $reference"
Write-Host "  Paquete: $archive"
Write-Host '  Entrega al cliente el paquete y un usuario con token de solo lectura (read:packages).'

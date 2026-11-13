<#
  Activa en el entorno de pruebas Contoso la funcionalidad completa de Sofibot con Microsoft
  Entra ID (solo equipos de Datasofi, con una aplicación de Entra ID de pruebas):

      .\examples\contoso\activar-entra.ps1

  Pide el id. de inquilino, el id. de aplicación y el secreto de cliente (el secreto no se
  muestra al escribirlo) y los escribe en examples/contoso/.env junto con:
  inicio de sesión con Entra ID, API de informes con Entra ID, servicio de consultas
  (perfil "consultas") y sus direcciones. El resto del .env se deja como estaba.
  Después reconstruye y arranca el entorno y abre el portal.

  Se puede volver a ejecutar: actualiza los valores. Para volver al modo sin inicio de
  sesión, poner SOFIBOT_AUTH=none en el .env y `docker compose ... up -d`.
#>
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$envFile = Join-Path $here '.env'
$compose = Join-Path $here 'compose.yaml'

if (-not (Test-Path $envFile)) {
    Write-Host "No existe $envFile. Ejecuta antes .\examples\contoso\preparar.ps1" -ForegroundColor Red
    exit 1
}

$guid = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
do { $tenant = (Read-Host 'Id. de directorio (inquilino)').Trim() } until ($tenant -match $guid)
do { $client = (Read-Host 'Id. de aplicación (cliente)').Trim() } until ($client -match $guid)
$secure = Read-Host 'Valor del secreto de cliente (no se muestra)' -AsSecureString
$secret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
if (-not $secret) { Write-Host 'El secreto está vacío: no se ha cambiado nada.' -ForegroundColor Red; exit 1 }

$lines = [System.Collections.Generic.List[string]]([IO.File]::ReadAllLines($envFile))
$profiles = @('consultas')
foreach ($line in $lines) {
    if ($line -match '^\s*COMPOSE_PROFILES\s*=\s*(.*)$') {
        $profiles += ($Matches[1] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
}
$settings = [ordered]@{
    'SOFIBOT_AUTH'             = 'entra'
    'SOFIBOT_PUBLIC_URL'       = 'http://localhost:8085'
    'ENTRA_TENANT_ID'          = $tenant
    'ENTRA_CLIENT_ID'          = $client
    'ENTRA_CLIENT_SECRET'      = $secret
    'SOFIBOT_CODE_API'         = 'entra'
    'COMPOSE_PROFILES'         = (($profiles | Select-Object -Unique) -join ',')
    'SOFIBOT_QUERY_URL'        = 'http://consultas:8080'
    'SOFIBOT_QUERY_PUBLIC_URL' = 'http://localhost:8086'
}
foreach ($key in $settings.Keys) {
    $value = "$key=$($settings[$key])"
    $index = -1
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match "^\s*#?\s*$key\s*=") { $index = $i; break } }
    if ($index -ge 0) { $lines[$index] = $value } else { $lines.Add($value) }
}
# UTF-8 sin BOM: Docker lee el BOM como parte del primer nombre de variable.
[IO.File]::WriteAllLines($envFile, $lines, (New-Object System.Text.UTF8Encoding($false)))
$secret = $null
Write-Host "Actualizado $envFile (los valores no se muestran)." -ForegroundColor Green

docker compose -f $compose up -d --build
if ($LASTEXITCODE -ne 0) { Write-Host 'docker compose ha fallado: revisa el mensaje de arriba.' -ForegroundColor Red; exit 1 }
Write-Host 'Portal: http://localhost:8085   Servicio de consultas: http://localhost:8086/health' -ForegroundColor Green
Start-Process 'http://localhost:8085'

<#
  Pipeline de prueba con Contoso: recrea la capa gold y regenera todos los informes.

      .\examples\contoso\refrescar.ps1
      .\examples\contoso\refrescar.ps1 -Database ContosoV2 -Portal http://localhost:8080

  1. Ejecuta 01-crear-gold.sql con tu usuario de Windows (debe poder crear tablas en la base).
  2. Pide al portal que regenere los informes (POST /api/admin/build-all con SOFIBOT_ADMIN_TOKEN de .env).
  El portal tiene que estar arrancado (docker compose up -d).
#>
param(
    [string]$Server = 'localhost',
    [string]$Database = 'ContosoRetailDW',
    [string]$Portal = 'http://localhost:8085'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "1/2 Capa gold en $Server/$Database..."
sqlcmd -S $Server -E -C -b -f 65001 -d $Database -i (Join-Path $PSScriptRoot '01-crear-gold.sql')
if ($LASTEXITCODE) { throw "Ha fallado la creación de la capa gold (código $LASTEXITCODE)" }

Write-Host "2/2 Regenerando informes en $Portal..."
$match = Select-String -Path (Join-Path $root '.env') -Pattern '^SOFIBOT_ADMIN_TOKEN=(.+)$'
if (-not $match) { throw 'Falta SOFIBOT_ADMIN_TOKEN en .env' }
$token = $match.Matches[0].Groups[1].Value
$result = Invoke-RestMethod -Method Post "$Portal/api/admin/build-all" -Headers @{ Authorization = "Bearer $token" }
$result.results.PSObject.Properties | ForEach-Object { "{0,-32} {1}" -f $_.Name, $_.Value }

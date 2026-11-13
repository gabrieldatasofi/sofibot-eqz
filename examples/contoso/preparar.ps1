<#
  Prepara el entorno de pruebas Contoso de un solo paso (solo equipos de Datasofi):

      .\examples\contoso\preparar.ps1
      .\examples\contoso\preparar.ps1 -Database ContosoV2 -Server 'localhost\SQLEXPRESS'

  1. Comprueba Docker y sqlcmd.
  2. Crea examples/contoso/.env si no existe, con contraseña y token generados (nunca se
     muestran). Si ya existe, lo reutiliza tal cual.
  3. Crea o actualiza el login sofibot_lectura en el SQL Server local con esa contraseña
     (sql/crear-login-lectura.sql, con tu usuario de Windows), y crea la capa gold si falta.
  4. Arranca el portal de pruebas, construye todos los informes y abre el navegador.

  Se puede volver a ejecutar siempre: deja login y .env sincronizados y reconstruye todo.
  Requisito: la base Contoso restaurada en ese SQL Server.
#>
param(
    [string]$Server = 'localhost',
    [string]$Database = 'ContosoRetailDW'
)
$ErrorActionPreference = 'Continue'  # errores de comandos externos: se comprueba $LASTEXITCODE
$here = $PSScriptRoot
$root = Split-Path -Parent (Split-Path -Parent $here)
$envFile = Join-Path $here '.env'
$compose = Join-Path $here 'compose.yaml'

function Fail([string]$message) { Write-Host "ERROR: $message" -ForegroundColor Red; exit 1 }
function Step([string]$message) { Write-Host "`n== $message" -ForegroundColor Cyan }
function New-Secret([int]$length, [string]$alphabet) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] $length
    $rng.GetBytes($bytes)
    -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
}
function New-SqlPassword {
    # Solo letras y números: mayúsculas, minúsculas y dígitos ya cumplen la política de Windows,
    # y ningún símbolo puede cambiar al pasar por Docker Compose, el .env o el SQL.
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    do { $value = New-Secret 28 $alphabet }
    until ($value -cmatch '[A-Z]' -and $value -cmatch '[a-z]' -and $value -match '\d')
    $value
}
function Read-EnvFile([string]$path) {
    $values = @{}
    foreach ($line in [IO.File]::ReadAllLines($path)) {
        if ($line -match '^\s*([A-Z_][A-Z0-9_]*)=(.*)$') {
            # Como Docker Compose: sin espacios alrededor y sin comillas que envuelvan el valor.
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and $value[0] -eq $value[-1] -and $value[0] -in '"', "'") { $value = $value.Substring(1, $value.Length - 2) }
            $values[$Matches[1]] = $value
        }
    }
    $values
}
function Set-Line([string]$text, [string]$pattern, [string]$line) {
    # Sustituye una línea completa; el texto nuevo es literal aunque lleve $.
    [regex]::Replace($text, $pattern, $line.Replace('$', '$$'))
}
function Write-Utf8NoBom([string]$path, [string]$text) {
    [IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

Step '1/4 Comprobando Docker y sqlcmd'
docker info *> $null
if ($LASTEXITCODE) { Fail 'Docker no responde. Abre Docker Desktop, espera a "Engine running" y vuelve a ejecutar el script.' }
if (-not (Get-Command sqlcmd -ErrorAction SilentlyContinue)) {
    Fail 'No se encuentra sqlcmd. Instala las herramientas de SQL Server (winget install Microsoft.Sqlcmd).'
}
sqlcmd -S $Server -E -C -b -Q "IF DB_ID(N'$Database') IS NULL THROW 50000, 'no existe', 1" *> $null
if ($LASTEXITCODE) { Fail "No se puede conectar a $Server con tu usuario de Windows, o la base $Database no existe en él." }

Step '2/4 Configuración (examples/contoso/.env)'
$b = New-Object byte[] 36
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
$token = [Convert]::ToBase64String($b) -replace '\+', '-' -replace '/', '_'
if (Test-Path $envFile) {
    # Se reutiliza; solo se generan la contraseña o el token si están vacíos.
    $text = [IO.File]::ReadAllText($envFile)
    $settings = Read-EnvFile $envFile
    $generated = @()
    foreach ($pair in @(@('SQLSERVER_PASSWORD', (New-SqlPassword)), @('SOFIBOT_ADMIN_TOKEN', $token))) {
        if ($settings[$pair[0]]) { continue }
        $pattern = "(?m)^$($pair[0])=[^\r\n]*"
        if ($text -match $pattern) { $text = Set-Line $text $pattern "$($pair[0])=$($pair[1])" }
        else { $text = $text.TrimEnd() + "`n$($pair[0])=$($pair[1])`n" }
        $generated += $pair[0]
    }
    if ($generated) {
        Write-Utf8NoBom $envFile $text
        Write-Host "Ya existía; generados los valores vacíos: $($generated -join ', ') (no se muestran)."
    } else {
        Write-Host 'Ya existe: se reutiliza.'
    }
} else {
    $template = [IO.File]::ReadAllText((Join-Path $here '.env.example'))
    $template = Set-Line $template '(?m)^SQLSERVER_DATABASE=[^\r\n]*' "SQLSERVER_DATABASE=$Database"
    $template = Set-Line $template '(?m)^SQLSERVER_PASSWORD=[^\r\n]*' "SQLSERVER_PASSWORD=$(New-SqlPassword)"
    $template = Set-Line $template '(?m)^SOFIBOT_ADMIN_TOKEN=[^\r\n]*' "SOFIBOT_ADMIN_TOKEN=$token"
    Write-Utf8NoBom $envFile $template
    Write-Host 'Creado con contraseña y token generados (no se muestran).'
}
$settings = Read-EnvFile $envFile
foreach ($key in 'SQLSERVER_USER', 'SQLSERVER_PASSWORD', 'SQLSERVER_DATABASE', 'SOFIBOT_ADMIN_TOKEN') {
    if (-not $settings[$key]) { Fail "Falta $key en examples/contoso/.env" }
}
if ($settings['SQLSERVER_DATABASE'] -ne $Database) {
    Fail "examples/contoso/.env apunta a $($settings['SQLSERVER_DATABASE']) y el script a $Database. Usa -Database $($settings['SQLSERVER_DATABASE']) o corrige el .env."
}

Step "3/4 Login de lectura y capa gold en $Server/$Database"
$gold = sqlcmd -S $Server -E -C -b -d $Database -h -1 -W -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM sys.tables WHERE SCHEMA_NAME(schema_id) = 'gold'"
if ($LASTEXITCODE) { Fail 'No se pudo comprobar el esquema gold.' }
if ([int]($gold | Select-Object -First 1) -lt 2) {
    Write-Host 'Creando la capa gold (01-crear-gold.sql)...'
    sqlcmd -S $Server -E -C -b -f 65001 -d $Database -i (Join-Path $here '01-crear-gold.sql')
    if ($LASTEXITCODE) { Fail 'Ha fallado 01-crear-gold.sql.' }
}
# Copia temporal del script con los valores puestos; se borra siempre, también si falla.
$sql = [IO.File]::ReadAllText((Join-Path $root 'sql\crear-login-lectura.sql'))
$quote = { param($value) $value.Replace("'", "''") }
$sql = Set-Line $sql "(?m)^DECLARE @login\s+sysname\s+= N'[^\r\n]*';" "DECLARE @login    sysname       = N'$(& $quote $settings['SQLSERVER_USER'])';"
$sql = Set-Line $sql "(?m)^DECLARE @password\s+nvarchar\(128\)\s+= N'[^\r\n]*';" "DECLARE @password nvarchar(128) = N'$(& $quote $settings['SQLSERVER_PASSWORD'])';"
$sql = Set-Line $sql "(?m)^DECLARE @database\s+sysname\s+= N'[^\r\n]*';" "DECLARE @database sysname       = N'$(& $quote $Database)';"
if ($sql -match "(?m)^DECLARE @(login|password|database)\s[^\r\n]*N'CAMBIAR") { Fail 'No se pudieron poner los valores en sql/crear-login-lectura.sql (¿ha cambiado su formato?).' }
$temp = Join-Path $env:TEMP ("sofibot-login-" + [guid]::NewGuid().ToString('N') + '.sql')
try {
    Write-Utf8NoBom $temp $sql
    sqlcmd -S $Server -E -C -b -f 65001 -i $temp
    if ($LASTEXITCODE) { Fail 'Ha fallado sql/crear-login-lectura.sql.' }
} finally {
    Remove-Item $temp -Force -ErrorAction SilentlyContinue
}

# El portal entra con usuario y contraseña de SQL Server por TCP: se prueba lo mismo antes de seguir.
$windowsOnly = sqlcmd -S $Server -E -C -b -h -1 -W -Q "SET NOCOUNT ON; SELECT CONVERT(int, SERVERPROPERTY('IsIntegratedSecurityOnly'))"
if (($windowsOnly | Select-Object -First 1) -eq '1') {
    Fail ("$Server solo admite usuarios de Windows, así que rechaza a $($settings['SQLSERVER_USER']). Actívalo en SSMS: " +
          "propiedades del servidor > Seguridad > 'Modo de autenticación de SQL Server y Windows', y reinicia el servicio " +
          "de SQL Server (Servicios de Windows o SQL Server Configuration Manager). Después vuelve a ejecutar este script.")
}
$sqlPort = if ($settings['SQLSERVER_PORT']) { $settings['SQLSERVER_PORT'] } else { '1433' }
$env:SQLCMDPASSWORD = $settings['SQLSERVER_PASSWORD']  # así la contraseña no va en la línea de comandos
try {
    sqlcmd -S "tcp:localhost,$sqlPort" -U $settings['SQLSERVER_USER'] -C -b -l 15 -d $Database -Q "SET NOCOUNT ON; SELECT 1" *> $null
    $loginOk = -not $LASTEXITCODE
} finally {
    Remove-Item Env:\SQLCMDPASSWORD -ErrorAction SilentlyContinue
}
if (-not $loginOk) {
    Write-Host "El login $($settings['SQLSERVER_USER']) no puede entrar por TCP en localhost:$sqlPort, que es como entra el portal." -ForegroundColor Yellow
    Write-Host 'Motivo según el registro de SQL Server (si ese puerto es de esta instancia):'
    sqlcmd -S $Server -E -C -h -1 -W -Q "SET NOCOUNT ON; CREATE TABLE #log (fecha datetime, origen nvarchar(50), texto nvarchar(4000)); INSERT #log EXEC xp_readerrorlog 0, 1, N'$($settings['SQLSERVER_USER'])'; SELECT TOP 3 CONVERT(varchar(19), fecha, 120) + '  ' + texto FROM #log ORDER BY fecha DESC"
    sqlcmd -S "tcp:localhost,$sqlPort" -E -C -b -l 15 -h -1 -W -Q "SET NOCOUNT ON; SELECT 'En localhost:$sqlPort responde: ' + @@SERVERNAME" 2>$null
    sqlcmd -S $Server -E -C -h -1 -W -Q "SET NOCOUNT ON; SELECT 'El script ha usado: ' + @@SERVERNAME"
    Fail ('Si los dos nombres de servidor son distintos, el puerto es de otra instancia: corrige SQLSERVER_HOST/SQLSERVER_PORT ' +
          'en examples/contoso/.env o usa -Server. Si el motivo dice "password did not match", revisa que SQLSERVER_PASSWORD ' +
          'no tenga comillas ni espacios al final.')
}
Write-Host "Comprobado: $($settings['SQLSERVER_USER']) entra por TCP en localhost:$sqlPort."

Step '4/4 Portal de pruebas e informes'
$port = if ($settings['SOFIBOT_PORT']) { $settings['SOFIBOT_PORT'] } else { '8085' }
$running = docker compose -f $compose ps -q sofibot 2>$null
if (-not $running -and (Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue)) {
    Fail "El puerto $port está ocupado (¿el portal del proyecto? ejecuta 'docker compose down' en la raíz) o cambia SOFIBOT_PORT en examples/contoso/.env."
}
docker compose -f $compose up -d --build
if ($LASTEXITCODE) { Fail 'No se pudo arrancar el portal de pruebas.' }

# Docker debe recibir la misma contraseña que se ha puesto al login: se comparan huellas, nunca el valor.
$sha = [Security.Cryptography.SHA256]::Create()
$expected = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($settings['SQLSERVER_PASSWORD']))) -replace '-', '').Substring(0, 16)
$seen = docker compose -f $compose run --rm --no-deps -T sofibot python -c "import os,hashlib;print(hashlib.sha256(os.environ.get('SQLSERVER_PASSWORD','').encode()).hexdigest()[:16].upper())" 2>$null |
    Select-Object -Last 1
if ($seen -ne $expected) {
    Fail ('Docker lee en examples/contoso/.env una contraseña distinta de la que se ha puesto al login. Suele ser una línea ' +
          'SQLSERVER_PASSWORD repetida o un símbolo ($, #, comillas) que Docker Compose interpreta. Deja una sola línea ' +
          '"SQLSERVER_PASSWORD=" vacía y vuelve a ejecutar el script: generará una nueva solo con letras y números.')
}
Write-Host 'Comprobado: Docker usa la misma contraseña que el login.'
docker compose -f $compose run --rm sofibot sofibot build --all
if ($LASTEXITCODE) { Fail 'Algún informe ha fallado: revisa el mensaje de arriba.' }

$url = "http://localhost:$port/dashboard"
for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-WebRequest "http://localhost:$port/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Seconds 2 }
}
Write-Host "`nListo: $url" -ForegroundColor Green
Start-Process $url

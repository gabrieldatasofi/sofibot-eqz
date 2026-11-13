﻿<#
  Construye mcp-server\dist\sofibot-mcp.exe: los dos conectores MCP de Sofibot y su
  instalador en un solo programa de Windows, para que los usuarios no instalen Python.

      .\mcp-server\build-exe.ps1
      .\mcp-server\build-exe.ps1 -Python 'C:\Python312\python.exe'

  Lo ejecuta Datasofi en un equipo Windows en cada versión nueva de los conectores y antes
  de construir la imagen de Sofibot: la imagen incluye el .exe y el portal lo ofrece en
  "Conectar tu IA". Usa entornos temporales: no toca nada más.

  Python: 3.12 de python.org o de Miniconda (por defecto, el que encuentra `py -3.12`). No
  sirve el Python interno de herramientas como Codex: su OpenSSL no funciona empaquetado. El
  script lo comprueba al final con `sofibot-mcp.exe comprobar`.
#>
param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
if (-not $Python) {
    $Python = (& py -3.12 -c 'import sys; print(sys.executable)' 2>$null)
    if (-not $Python) { throw 'No encuentro Python 3.12 (py -3.12). Instálalo o indica -Python <ruta a python.exe>' }
}
Write-Host "Python: $Python"
$work = Join-Path ([IO.Path]::GetTempPath()) "sofibot-mcp-build"
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
New-Item -ItemType Directory $work | Out-Null

& $Python -m venv (Join-Path $work 'venv')
if ($LASTEXITCODE -ne 0) { throw "No se ha podido crear el entorno con '$Python'" }
$py = Join-Path $work 'venv\Scripts\python.exe'
& $py -m pip install --quiet -r (Join-Path $here 'requirements.txt') 'pyinstaller==6.11.1'
if ($LASTEXITCODE -ne 0) { throw 'pip install ha fallado' }

Push-Location $here
try {
    & $py -m PyInstaller --noconfirm --onefile --name sofibot-mcp `
        --distpath (Join-Path $here 'dist') --workpath (Join-Path $work 'build') --specpath $work `
        codigo_del_programa.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller ha fallado' }
} finally {
    Pop-Location
}
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
$exe = Join-Path $here 'dist\sofibot-mcp.exe'
& $exe comprobar
if ($LASTEXITCODE -ne 0) {
    Remove-Item $exe
    throw "El .exe no puede abrir conexiones seguras con este Python ($Python). Usa Python 3.12 de python.org o Miniconda."
}
Write-Host "Listo: $exe ($([math]::Round((Get-Item $exe).Length / 1MB)) MB)" -ForegroundColor Green

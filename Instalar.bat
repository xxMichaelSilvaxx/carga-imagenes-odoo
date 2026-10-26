<# :
@echo off
rem Archivo híbrido: cmd ejecuta solo este bloque y PowerShell ejecuta el resto del archivo.
setlocal
set "SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex ([IO.File]::ReadAllText($env:SELF, [Text.Encoding]::UTF8))"
exit /b %errorlevel%
#>

# Instala o actualiza "Carga de imágenes a Odoo" desde GitHub en %LOCALAPPDATA%\CargaImagenesOdoo.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Repo = 'xxMichaelSilvaxx/carga-imagenes-odoo'
$Branch = 'main'
$AppDir = Join-Path $env:LOCALAPPDATA 'CargaImagenesOdoo\app'
$LocalSource = Join-Path (Split-Path $env:SELF) 'codigo_fuente_aplicativo'

function Find-Python {
    # En PowerShell 5.1, 2>$null con 'Stop' convierte el stderr del ejecutable en una excepción
    $ErrorActionPreference = 'Continue'
    $candidates = @(
        @{ Exe = 'py'; Args = @('-3') },
        @{ Exe = 'python'; Args = @() },
        @{ Exe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"; Args = @() }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        & $candidate.Exe @($candidate.Args) -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
}

function Install-Python {
    Write-Host 'No se encontró Python 3.10 o superior en este equipo.' -ForegroundColor Yellow
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Descargue Python desde https://www.python.org/downloads/, marque "Add python.exe to PATH" y vuelva a ejecutar Instalar.bat.'
    }
    if ((Read-Host '¿Desea descargar e instalar Python 3.12 ahora? (S/N)') -notmatch '^[sS]') {
        throw 'La instalación necesita Python 3.10 o superior.'
    }
    winget install --exact --id Python.Python.3.12 --scope user
    # winget no actualiza el PATH de esta ventana
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Get-Source {
    if (Test-Path (Join-Path $LocalSource 'installer.py')) { return $LocalSource }
    Write-Host 'Descargando la última versión del aplicativo...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $zip = Join-Path $env:TEMP 'carga-imagenes-odoo.zip'
    $extract = Join-Path $env:TEMP 'carga-imagenes-odoo'
    Invoke-WebRequest -UseBasicParsing "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive $zip $extract -Force
    $root = Get-ChildItem $extract -Directory | Select-Object -First 1
    return Join-Path $root.FullName 'codigo_fuente_aplicativo'
}

try {
    Write-Host 'Carga de imágenes a Odoo - instalador' -ForegroundColor Cyan
    $python = Find-Python
    if (-not $python) {
        Install-Python
        $python = Find-Python
        if (-not $python) { throw 'Python se instaló, pero esta ventana aún no lo encuentra. Cierre la ventana y vuelva a ejecutar Instalar.bat.' }
    }
    $source = Get-Source
    New-Item -ItemType Directory -Force $AppDir | Out-Null
    # Solo se copian los archivos del aplicativo: el .venv existente se conserva entre actualizaciones
    Get-ChildItem $source -File | Copy-Item -Destination $AppDir -Force
    Write-Host 'Instalando componentes (se abrirá una ventana con el avance)...'
    & $python.Exe @($python.Args) (Join-Path $AppDir 'installer.py')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar los componentes. Revise la conexión a internet y vuelva a intentarlo.' }
} catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host 'Presione Enter para cerrar'
    exit 1
}

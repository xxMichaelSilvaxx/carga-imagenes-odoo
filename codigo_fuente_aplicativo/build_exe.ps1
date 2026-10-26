# Builds dist\CargaImagenesOdoo.exe (single file, no console) to hand out to the staff.
Set-Location $PSScriptRoot

function Invoke-Step($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Fallo: $exe $arguments" }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Invoke-Step "py" @("-3.11", "-m", "venv", ".venv")
}
Invoke-Step ".\.venv\Scripts\python.exe" @("-m", "pip", "install", "-q", "-r", "requirements.txt", "pyinstaller")
# PyInstaller logs to stderr; Windows PowerShell 5.1 would turn that into errors
$ErrorActionPreference = "Continue"
Invoke-Step ".\.venv\Scripts\pyinstaller.exe" @(
    "--noconfirm", "--clean", "--onefile", "--windowed", "--log-level", "WARN",
    "--name", "CargaImagenesOdoo", "--icon", "icon.ico", "--add-data", "icon.ico;.", "--add-data", "icon.png;.",
    "--hidden-import", "PIL._webp", "--collect-data", "sv_ttk", "carga_imagenes.py"
)
Write-Host "Listo: $PSScriptRoot\dist\CargaImagenesOdoo.exe"

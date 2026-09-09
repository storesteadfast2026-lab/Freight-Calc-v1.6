<#
.SYNOPSIS
  Crea un ZIP liviano del proyecto STH Freight Calculator para subirlo a ChatGPT y analizar el codigo actual.

.DESCRIPTION
  Ejecutar desde la raiz del proyecto:
    C:\Docker-Projects\Freight-Calc-05jun

  Este script copia solo los archivos importantes para revision:
    - app
    - tools
    - docs
    - reports
    - docker-compose.yml
    - Dockerfile
    - requirements.txt
    - manage.py
    - README.md

  Luego elimina carpetas y archivos pesados/innecesarios:
    - .venv, venv, env
    - __pycache__, .pytest_cache, .mypy_cache
    - .git, node_modules
    - staticfiles, media
    - .pyc, .sqlite3, .db, .log, .xlsx, .xlsm, .zip, .7z, .rar

  Resultado:
    .\sth_current_code_review.zip
#>

param(
    [string]$OutputZip = "Create_Files_Review.zip",
    [string]$WorkDir = "_upload_review"
)

$ErrorActionPreference = "Stop"

Write-Host "STH Freight Calculator - Review ZIP builder" -ForegroundColor Cyan
Write-Host "Project root: $(Get-Location)" -ForegroundColor Gray

# Validacion minima para evitar ejecutar en una carpeta incorrecta.
if (!(Test-Path ".\app")) {
    throw "No se encontro la carpeta .\app. Ejecuta este script desde la raiz del proyecto, por ejemplo: C:\Docker-Projects\Freight-Calc-05jun"
}

# Limpiar carpeta temporal.
if (Test-Path ".\$WorkDir") {
    Write-Host "Removing previous $WorkDir..." -ForegroundColor Yellow
    Remove-Item ".\$WorkDir" -Recurse -Force -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory ".\$WorkDir" | Out-Null

# Copiar carpetas relevantes.
$folders = @("app", "tools", "docs", "reports")
foreach ($folder in $folders) {
    if (Test-Path ".\$folder") {
        Write-Host "Copying folder: $folder" -ForegroundColor Green
        Copy-Item ".\$folder" ".\$WorkDir\$folder" -Recurse -Force
    }
}

# Copiar archivos raiz relevantes.
$rootFiles = @("docker-compose.yml", "Dockerfile", "requirements.txt", "manage.py", "README.md", ".env.example")
foreach ($file in $rootFiles) {
    if (Test-Path ".\$file") {
        Write-Host "Copying file: $file" -ForegroundColor Green
        Copy-Item ".\$file" ".\$WorkDir\" -Force
    }
}

# Eliminar directorios pesados o innecesarios dentro de la copia.
$removeDirs = @(
    ".venv", "venv", "env",
    "__pycache__", ".pytest_cache", ".mypy_cache",
    ".git", "node_modules",
    "staticfiles", "media"
)

Get-ChildItem ".\$WorkDir" -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $removeDirs -contains $_.Name } |
    ForEach-Object {
        Write-Host "Removing folder: $($_.FullName)" -ForegroundColor DarkYellow
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }

# Eliminar archivos pesados/innecesarios dentro de la copia.
$removeExtensions = @(
    ".pyc", ".pyo",
    ".sqlite3", ".db",
    ".log",
    ".xlsx", ".xlsm",
    ".zip", ".7z", ".rar"
)

Get-ChildItem ".\$WorkDir" -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $removeExtensions -contains $_.Extension.ToLowerInvariant() } |
    ForEach-Object {
        Write-Host "Removing file: $($_.FullName)" -ForegroundColor DarkYellow
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }

# Crear ZIP.
if (Test-Path ".\$OutputZip") {
    Remove-Item ".\$OutputZip" -Force -ErrorAction SilentlyContinue
}

Write-Host "Creating ZIP: $OutputZip" -ForegroundColor Cyan
Compress-Archive -Path ".\$WorkDir\*" -DestinationPath ".\$OutputZip" -Force

$zipItem = Get-Item ".\$OutputZip"
$sizeMb = [Math]::Round($zipItem.Length / 1MB, 2)

Write-Host "" 
Write-Host "OK: ZIP created" -ForegroundColor Green
Write-Host "File: $($zipItem.FullName)" -ForegroundColor Green
Write-Host "Size: $sizeMb MB" -ForegroundColor Green
Write-Host "" 
Write-Host "Upload this file to ChatGPT when code review is needed:" -ForegroundColor Cyan
Write-Host $zipItem.FullName -ForegroundColor White

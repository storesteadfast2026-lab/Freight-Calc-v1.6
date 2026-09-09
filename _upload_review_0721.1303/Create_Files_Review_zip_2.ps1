<#
.SYNOPSIS
  Crea un ZIP seguro y completo para revisar el codigo actual de STH Freight Calculator con una IA.

.DESCRIPTION
  Ejecuta este script desde la raiz del proyecto Django, por ejemplo:

    C:\Docker-Projects\Freight-Calc-Nuevo

  El paquete incluye:
    - Codigo Django/Python, templates, JavaScript, CSS, migraciones y pruebas.
    - Configuracion de Docker e instalacion disponible en la raiz.
    - Documentacion y reportes, salvo que se indique -SkipReports.
    - Archivos Excel de referencia conocidos, si estan disponibles, salvo que se indique -SkipReferenceFiles.
    - Arbol del proyecto, estado Git, chequeo Django, migraciones, resumen no sensible de la base y resultados de pruebas.

  El paquete excluye:
    - Entornos virtuales, caches, .git, node_modules y archivos generados.
    - .env reales, credenciales, certificados, claves privadas y dumps de base de datos.
    - media, uploaded_data, staticfiles, logs y ZIP anteriores.
    - Un backup completo de PostgreSQL.

  La inclusion de archivos Excel es controlada: solo se buscan los tres archivos de referencia conocidos.

.EXAMPLE
  .\Create_Files_Review_zip_0721.0327.ps1

.EXAMPLE
  .\Create_Files_Review_zip_0721.0327.ps1 -SkipTests

.EXAMPLE
  .\Create_Files_Review_zip_0721.0327.ps1 -SkipReferenceFiles -SkipReports
#>

[CmdletBinding()]
param(
    [string]$OutputZip = ("sth_current_code_review_{0}.zip" -f (Get-Date -Format "MMdd.HHmm")),
    [string]$WorkDir = ("_upload_review_{0}" -f (Get-Date -Format "MMdd.HHmm")),
    [switch]$SkipReferenceFiles,
    [switch]$SkipReports,
    [switch]$SkipRuntimeDiagnostics,
    [switch]$SkipTests,
    [switch]$KeepWorkDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$ProjectRoot = (Get-Location).Path
$WorkPath = Join-Path $ProjectRoot $WorkDir

if ([System.IO.Path]::IsPathRooted($OutputZip)) {
    $ZipPath = $OutputZip
}
else {
    $ZipPath = Join-Path $ProjectRoot $OutputZip
}

if ([System.IO.Path]::GetExtension($ZipPath) -ne ".zip") {
    $ZipPath = "$ZipPath.zip"
}

$ZipParent = Split-Path -Parent $ZipPath
if ($ZipParent -and !(Test-Path $ZipParent)) {
    New-Item -ItemType Directory -Path $ZipParent -Force | Out-Null
}

$ExcludedLog = New-Object System.Collections.Generic.List[string]
$ReferenceLog = New-Object System.Collections.Generic.List[string]

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan
}

function Add-ExcludedItem {
    param(
        [string]$Path,
        [string]$Reason
    )

    $relative = $Path
    if ($Path.StartsWith($WorkPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relative = $Path.Substring($WorkPath.Length).TrimStart([char[]]'\/')
    }

    $ExcludedLog.Add("$relative`t$Reason") | Out-Null
}

function Remove-TrackedItem {
    param(
        [System.IO.FileSystemInfo]$Item,
        [string]$Reason
    )

    Add-ExcludedItem -Path $Item.FullName -Reason $Reason
    Remove-Item -LiteralPath $Item.FullName -Recurse -Force -ErrorAction SilentlyContinue
}

function Copy-RootMatches {
    param([string[]]$Patterns)

    foreach ($pattern in $Patterns) {
        Get-ChildItem -Path $ProjectRoot -File -Force -Filter $pattern -ErrorAction SilentlyContinue |
            Where-Object {
                $_.FullName -ne $ZipPath -and
                !$_.FullName.StartsWith($WorkPath, [System.StringComparison]::OrdinalIgnoreCase)
            } |
            ForEach-Object {
                Write-Host "Copying root file: $($_.Name)" -ForegroundColor Green
                Copy-Item -LiteralPath $_.FullName -Destination $WorkPath -Force
            }
    }
}

function Invoke-CommandToFile {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$OutputFile,
        [string]$Title
    )

    $target = Join-Path $WorkPath $OutputFile
    "# $Title" | Out-File -FilePath $target -Encoding utf8
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')" | Out-File -FilePath $target -Append -Encoding utf8
    "Command: $Executable $($Arguments -join ' ')" | Out-File -FilePath $target -Append -Encoding utf8
    "" | Out-File -FilePath $target -Append -Encoding utf8

    try {
        $output = & $Executable @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        $output | Out-File -FilePath $target -Append -Encoding utf8
        "" | Out-File -FilePath $target -Append -Encoding utf8
        "Exit code: $exitCode" | Out-File -FilePath $target -Append -Encoding utf8
        return $exitCode
    }
    catch {
        "FAILED TO EXECUTE: $($_.Exception.Message)" | Out-File -FilePath $target -Append -Encoding utf8
        return 999
    }
}

function Find-ReferenceFile {
    param(
        [string]$FileName,
        [string[]]$PreferredPaths
    )

    foreach ($candidate in $PreferredPaths) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $found = Get-ChildItem -Path $ProjectRoot -Recurse -File -Force -Filter $FileName -ErrorAction SilentlyContinue |
        Where-Object {
            !$_.FullName.StartsWith($WorkPath, [System.StringComparison]::OrdinalIgnoreCase) -and
            $_.FullName -ne $ZipPath
        } |
        Select-Object -First 1

    if ($found) {
        return $found.FullName
    }

    return $null
}

Write-Host "STH Freight Calculator - AI review ZIP builder" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray
Write-Host "Output ZIP:   $ZipPath" -ForegroundColor Gray

if (!(Test-Path (Join-Path $ProjectRoot "app") -PathType Container)) {
    throw "No se encontro la carpeta .\app. Ejecuta el script desde la raiz del proyecto Django."
}

if (!(Test-Path (Join-Path $ProjectRoot "manage.py") -PathType Leaf) -and
    !(Test-Path (Join-Path $ProjectRoot "app\manage.py") -PathType Leaf)) {
    Write-Warning "No se encontro manage.py en la raiz ni en .\app. El codigo se empaquetara, pero no se podran ejecutar diagnosticos locales."
}

Write-Section "1. Preparing temporary review directory"

if (Test-Path -LiteralPath $WorkPath) {
    Write-Host "Removing previous work directory: $WorkPath" -ForegroundColor Yellow
    Remove-Item -LiteralPath $WorkPath -Recurse -Force
}

New-Item -ItemType Directory -Path $WorkPath -Force | Out-Null

Write-Section "2. Copying source code and documentation"

$folders = @("app", "tools", "docs", "scripts", "tests")
if (!$SkipReports) {
    $folders += "reports"
}

foreach ($folder in $folders) {
    $source = Join-Path $ProjectRoot $folder
    if (Test-Path -LiteralPath $source -PathType Container) {
        Write-Host "Copying folder: $folder" -ForegroundColor Green
        Copy-Item -LiteralPath $source -Destination (Join-Path $WorkPath $folder) -Recurse -Force
    }
}

$rootPatterns = @(
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "compose*.yml",
    "compose*.yaml",
    "Dockerfile*",
    "requirements*.txt",
    "manage.py",
    "README*",
    ".env*.example",
    ".gitignore",
    ".dockerignore",
    "pyproject.toml",
    "pytest.ini",
    "tox.ini",
    "gunicorn*.py",
    "Makefile",
    "*.ps1"
)
Copy-RootMatches -Patterns $rootPatterns

Write-Section "3. Removing generated, heavy, and sensitive content"

$removeDirectoryNames = @(
    ".venv", "venv", "env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".coverage",
    ".git", ".idea", ".vscode", "node_modules",
    "staticfiles", "media", "uploaded_data", "uploads",
    "htmlcov", "coverage", "dist", "build"
)

$directoriesToRemove = Get-ChildItem -Path $WorkPath -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $removeDirectoryNames -contains $_.Name } |
    Sort-Object { $_.FullName.Length } -Descending

foreach ($directory in $directoriesToRemove) {
    if (Test-Path -LiteralPath $directory.FullName) {
        Write-Host "Removing folder: $($directory.FullName)" -ForegroundColor DarkYellow
        Remove-TrackedItem -Item $directory -Reason "Generated, local, uploaded, or unnecessary directory"
    }
}

$removeExtensions = @(
    ".pyc", ".pyo",
    ".sqlite3", ".db", ".dump", ".sql",
    ".log",
    ".zip", ".7z", ".rar",
    ".pem", ".key", ".pfx", ".p12", ".jks",
    ".bak", ".tmp", ".swp",
    ".xlsx", ".xlsm", ".xls"
)

$filesToRemove = Get-ChildItem -Path $WorkPath -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $removeExtensions -contains $_.Extension.ToLowerInvariant() }

foreach ($file in $filesToRemove) {
    Write-Host "Removing file: $($file.FullName)" -ForegroundColor DarkYellow
    Remove-TrackedItem -Item $file -Reason "Binary, generated, database, secret, backup, archive, or non-controlled spreadsheet"
}

$sensitiveFiles = Get-ChildItem -Path $WorkPath -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $name = $_.Name.ToLowerInvariant()
        (($name -like ".env*") -and ($name -notlike "*.example")) -or
        ($name -match "^(credentials?|secrets?|private[_-]?key).*") -or
        ($name -match ".*\.(kdbx|ovpn)$")
    }

foreach ($file in $sensitiveFiles) {
    Write-Host "Removing sensitive file: $($file.FullName)" -ForegroundColor Red
    Remove-TrackedItem -Item $file -Reason "Potential secret or credential file"
}

Write-Section "4. Adding controlled Excel reference files"

$referenceDir = Join-Path $WorkPath "reference_files"

if (!$SkipReferenceFiles) {
    New-Item -ItemType Directory -Path $referenceDir -Force | Out-Null

    $referenceSpecs = @(
        @{
            Name = "V2026.R2_Unlocked_STH_Freight_Calculator.xlsx"
            Paths = @(
                (Join-Path $ProjectRoot "sample_data\V2026.R2_Unlocked_STH_Freight_Calculator.xlsx"),
                (Join-Path $ProjectRoot "app\sample_data\V2026.R2_Unlocked_STH_Freight_Calculator.xlsx"),
                (Join-Path $ProjectRoot "V2026.R2_Unlocked_STH_Freight_Calculator.xlsx")
            )
        },
        @{
            Name = "product_sth.xlsx"
            Paths = @(
                "T:\Steadfast\Excel Files\STH_FGT_CALC\product_sth.xlsx",
                (Join-Path $ProjectRoot "sample_data\product_sth.xlsx"),
                (Join-Path $ProjectRoot "app\sample_data\product_sth.xlsx"),
                (Join-Path $ProjectRoot "product_sth.xlsx")
            )
        },
        @{
            Name = "stock_sth.xlsx"
            Paths = @(
                "T:\Steadfast\Excel Files\STH_FGT_CALC\stock_sth.xlsx",
                (Join-Path $ProjectRoot "sample_data\stock_sth.xlsx"),
                (Join-Path $ProjectRoot "app\sample_data\stock_sth.xlsx"),
                (Join-Path $ProjectRoot "stock_sth.xlsx")
            )
        }
    )

    foreach ($spec in $referenceSpecs) {
        $sourceFile = Find-ReferenceFile -FileName $spec.Name -PreferredPaths $spec.Paths
        if ($sourceFile) {
            $destination = Join-Path $referenceDir $spec.Name
            Copy-Item -LiteralPath $sourceFile -Destination $destination -Force
            $hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
            $ReferenceLog.Add("INCLUDED`t$($spec.Name)`t$sourceFile`tSHA256=$hash") | Out-Null
            Write-Host "Included reference file: $($spec.Name)" -ForegroundColor Green
        }
        else {
            $ReferenceLog.Add("NOT FOUND`t$($spec.Name)") | Out-Null
            Write-Warning "Reference file not found: $($spec.Name)"
        }
    }

    if (@(Get-ChildItem -Path $referenceDir -File -ErrorAction SilentlyContinue).Count -eq 0) {
        Remove-Item -LiteralPath $referenceDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
else {
    $ReferenceLog.Add("SKIPPED BY PARAMETER`tAll reference spreadsheets") | Out-Null
}

$ReferenceLog | Out-File -FilePath (Join-Path $WorkPath "REFERENCE_FILES.txt") -Encoding utf8

Write-Section "5. Capturing Git state"

$gitFile = Join-Path $WorkPath "GIT_STATE.txt"
$gitCommand = Get-Command git -ErrorAction SilentlyContinue

if ($gitCommand) {
    "# Git state" | Out-File -FilePath $gitFile -Encoding utf8
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')" | Out-File -FilePath $gitFile -Append -Encoding utf8

    $branch = & git -C $ProjectRoot branch --show-current 2>&1
    $commit = & git -C $ProjectRoot rev-parse HEAD 2>&1
    $lastCommit = & git -C $ProjectRoot log -1 --format="%h | %ad | %an | %s" --date=iso-strict 2>&1
    $status = & git -C $ProjectRoot status --short 2>&1

    "Branch: $branch" | Out-File -FilePath $gitFile -Append -Encoding utf8
    "Commit: $commit" | Out-File -FilePath $gitFile -Append -Encoding utf8
    "Last commit: $lastCommit" | Out-File -FilePath $gitFile -Append -Encoding utf8
    "" | Out-File -FilePath $gitFile -Append -Encoding utf8
    "Modified/untracked files:" | Out-File -FilePath $gitFile -Append -Encoding utf8
    if ($status) {
        $status | Out-File -FilePath $gitFile -Append -Encoding utf8
    }
    else {
        "Working tree clean" | Out-File -FilePath $gitFile -Append -Encoding utf8
    }
}
else {
    "Git is not available. Git metadata was not collected." | Out-File -FilePath $gitFile -Encoding utf8
}

Write-Section "6. Capturing Django/runtime diagnostics"

$diagnosticMode = "none"
$dockerAvailable = [bool](Get-Command docker -ErrorAction SilentlyContinue)
$webRunning = $false

if (!$SkipRuntimeDiagnostics -and $dockerAvailable) {
    try {
        $runningServices = @(& docker compose ps --status running --services 2>$null)
        if ($LASTEXITCODE -eq 0 -and ($runningServices -contains "web")) {
            $webRunning = $true
            $diagnosticMode = "docker"
        }
    }
    catch {
        $webRunning = $false
    }
}

$localPython = Get-Command python -ErrorAction SilentlyContinue
$managePath = $null
if (Test-Path (Join-Path $ProjectRoot "manage.py") -PathType Leaf) {
    $managePath = "manage.py"
}
elseif (Test-Path (Join-Path $ProjectRoot "app\manage.py") -PathType Leaf) {
    $managePath = "app/manage.py"
}

if (!$SkipRuntimeDiagnostics -and !$webRunning -and $localPython -and $managePath) {
    $diagnosticMode = "local"
}

if ($SkipRuntimeDiagnostics) {
    "Runtime diagnostics were skipped by parameter." | Out-File -FilePath (Join-Path $WorkPath "RUNTIME_DIAGNOSTICS.txt") -Encoding utf8
}
elif ($diagnosticMode -eq "docker") {
    Write-Host "Using running Docker service: web" -ForegroundColor Green

    Invoke-CommandToFile -Executable "docker" -Arguments @("compose", "exec", "-T", "web", "python", "manage.py", "check") -OutputFile "DJANGO_CHECK.txt" -Title "Django system check" | Out-Null
    Invoke-CommandToFile -Executable "docker" -Arguments @("compose", "exec", "-T", "web", "python", "manage.py", "showmigrations") -OutputFile "MIGRATIONS_STATUS.txt" -Title "Applied Django migrations" | Out-Null

    $dbSummaryCode = @'
from django.apps import apps

specs = [
    ("clients", "Client"),
    ("products", "Product"),
    ("locations", "Suburb"),
    ("rates", "FreightZone"),
    ("rates", "FreightRate"),
    ("carriers", "ClientCarrierConfig"),
    ("imports", "ExternalDataFile"),
    ("imports", "ProductSourceRow"),
    ("imports", "StockSourceRow"),
    ("audit", "AuditEvent"),
]

print("NON-SENSITIVE DATABASE SUMMARY")
for app_label, model_name in specs:
    try:
        model = apps.get_model(app_label, model_name)
        print(f"{app_label}.{model_name}: {model.objects.count()}")
    except Exception as exc:
        print(f"{app_label}.{model_name}: unavailable ({exc.__class__.__name__})")

try:
    Client = apps.get_model("clients", "Client")
    print("Client codes:", ", ".join(Client.objects.order_by("code").values_list("code", flat=True)))
except Exception as exc:
    print("Client codes: unavailable", exc.__class__.__name__)
'@

    Invoke-CommandToFile -Executable "docker" -Arguments @("compose", "exec", "-T", "web", "python", "manage.py", "shell", "-c", $dbSummaryCode) -OutputFile "DATABASE_SUMMARY.txt" -Title "Non-sensitive database row counts" | Out-Null

    if (!$SkipTests) {
        Invoke-CommandToFile -Executable "docker" -Arguments @("compose", "exec", "-T", "web", "python", "manage.py", "test", "-v", "2") -OutputFile "TEST_RESULTS.txt" -Title "Complete Django test suite" | Out-Null
    }
    else {
        "Tests were skipped by parameter." | Out-File -FilePath (Join-Path $WorkPath "TEST_RESULTS.txt") -Encoding utf8
    }
}
elif ($diagnosticMode -eq "local") {
    Write-Host "Docker web service not available. Using local Python." -ForegroundColor Yellow

    Invoke-CommandToFile -Executable $localPython.Path -Arguments @($managePath, "check") -OutputFile "DJANGO_CHECK.txt" -Title "Django system check" | Out-Null
    Invoke-CommandToFile -Executable $localPython.Path -Arguments @($managePath, "showmigrations") -OutputFile "MIGRATIONS_STATUS.txt" -Title "Applied Django migrations" | Out-Null

    "Database summary was not collected automatically in local mode." | Out-File -FilePath (Join-Path $WorkPath "DATABASE_SUMMARY.txt") -Encoding utf8

    if (!$SkipTests) {
        Invoke-CommandToFile -Executable $localPython.Path -Arguments @($managePath, "test", "-v", "2") -OutputFile "TEST_RESULTS.txt" -Title "Complete Django test suite" | Out-Null
    }
    else {
        "Tests were skipped by parameter." | Out-File -FilePath (Join-Path $WorkPath "TEST_RESULTS.txt") -Encoding utf8
    }
}
else {
    $message = @"
Runtime diagnostics could not be collected.
Docker service 'web' was not running and no usable local Python/manage.py combination was found.
The source package is still valid for static code review.
"@
    $message | Out-File -FilePath (Join-Path $WorkPath "RUNTIME_DIAGNOSTICS.txt") -Encoding utf8
    $message | Out-File -FilePath (Join-Path $WorkPath "DJANGO_CHECK.txt") -Encoding utf8
    $message | Out-File -FilePath (Join-Path $WorkPath "MIGRATIONS_STATUS.txt") -Encoding utf8
    $message | Out-File -FilePath (Join-Path $WorkPath "DATABASE_SUMMARY.txt") -Encoding utf8
    $message | Out-File -FilePath (Join-Path $WorkPath "TEST_RESULTS.txt") -Encoding utf8
}

Write-Section "7. Creating review manifests"

$readme = @"
STH FREIGHT CALCULATOR - AI REVIEW PACKAGE
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')
Project root used: $ProjectRoot

PURPOSE
This ZIP is intended for complete source-code and architecture review by an AI or another developer.

INCLUDED
- Django/Python application code.
- Original templates, JavaScript and CSS.
- Models, migrations, admin configuration, services and tests.
- Docker and installation configuration found at the project root.
- Documentation and optional reports.
- Controlled reference spreadsheets when found.
- Git state, project tree, Django checks, migration status, non-sensitive database counts and test results.

EXCLUDED FOR SAFETY OR SIZE
- Real .env files and credential files.
- Private keys, certificates and database dumps.
- .git history, virtual environments, caches and generated static files.
- Uploaded media and historical imported files.
- Complete PostgreSQL data.
- Arbitrary spreadsheets. Only the three known reference files may be included.

IMPORTANT
Reference spreadsheets and reports can contain business information. Review the ZIP before sending it outside the organization.
The DATABASE_SUMMARY file contains row counts only, not table contents.
"@
$readme | Out-File -FilePath (Join-Path $WorkPath "README_REVIEW_PACKAGE.txt") -Encoding utf8

$ExcludedLog | Sort-Object | Out-File -FilePath (Join-Path $WorkPath "EXCLUDED_FILES.txt") -Encoding utf8

$workRootResolved = (Resolve-Path -LiteralPath $WorkPath).Path
Get-ChildItem -Path $WorkPath -Recurse -Force -ErrorAction SilentlyContinue |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($workRootResolved.Length).TrimStart([char[]]'\/')
        if ($_.PSIsContainer) {
            "[DIR]  $relative"
        }
        else {
            "[FILE] $relative"
        }
    } |
    Out-File -FilePath (Join-Path $WorkPath "PROJECT_TREE.txt") -Encoding utf8

$manifestPath = Join-Path $WorkPath "INCLUDED_FILES_SHA256.txt"
"RelativePath`tSizeBytes`tSHA256" | Out-File -FilePath $manifestPath -Encoding utf8

Get-ChildItem -Path $WorkPath -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -ne $manifestPath } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($workRootResolved.Length).TrimStart([char[]]'\/')
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$relative`t$($_.Length)`t$hash" | Out-File -FilePath $manifestPath -Append -Encoding utf8
    }

Write-Section "8. Creating ZIP"

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Compress-Archive -Path (Join-Path $WorkPath "*") -DestinationPath $ZipPath -CompressionLevel Optimal -Force

$zipItem = Get-Item -LiteralPath $ZipPath
$zipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sizeMb = [Math]::Round($zipItem.Length / 1MB, 2)

Write-Host ""
Write-Host "OK: review ZIP created" -ForegroundColor Green
Write-Host "File:   $($zipItem.FullName)" -ForegroundColor Green
Write-Host "Size:   $sizeMb MB" -ForegroundColor Green
Write-Host "SHA256: $zipHash" -ForegroundColor Green
Write-Host ""
Write-Host "Before sharing, open the ZIP and review README_REVIEW_PACKAGE.txt and REFERENCE_FILES.txt." -ForegroundColor Cyan

if (!$KeepWorkDir) {
    Remove-Item -LiteralPath $WorkPath -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Temporary directory removed: $WorkPath" -ForegroundColor Gray
}
else {
    Write-Host "Temporary directory kept: $WorkPath" -ForegroundColor Gray
}

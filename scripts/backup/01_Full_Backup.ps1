[CmdletBinding()]
param(
    [string]$ProjectRoot = "C:\Docker-Projects\Freight-Calc-v1.5",
    [string]$BackupRoot = "C:\Docker-Backups\Freight-Calc",
    [string]$DbService = "db",
    [string]$DbName = "freight_platform",
    [string]$DbUser = "freight_user",
    [string]$SecondaryCopyPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-ExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Get-Sha256 {
    param([string]$Path)
    (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

if (-not (Test-Path $ProjectRoot)) {
    throw "Project root does not exist: $ProjectRoot"
}

Set-Location $ProjectRoot

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFolder = Join-Path $BackupRoot "backup_$timestamp"
$dbFolder = Join-Path $backupFolder "postgresql"
$gitFolder = Join-Path $backupFolder "git"
$logFolder = Join-Path $backupFolder "logs"

New-Item -ItemType Directory -Force -Path $dbFolder, $gitFolder, $logFolder | Out-Null

$logPath = Join-Path $logFolder "01_Full_Backup_$timestamp.log"
Start-Transcript -Path $logPath -Force | Out-Null

try {
    Write-Host "============================================================"
    Write-Host " FREIGHT CALCULATOR - FULL RECOVERY POINT"
    Write-Host "============================================================"
    Write-Host "Project       : $ProjectRoot"
    Write-Host "Backup folder : $backupFolder"

    Write-Host "`n=== PRE-FLIGHT ==="
    docker compose ps
    Assert-ExitCode "docker compose ps"

    $dbContainer = (docker compose ps -q $DbService).Trim()
    Assert-ExitCode "docker compose ps -q $DbService"
    if ([string]::IsNullOrWhiteSpace($dbContainer)) {
        throw "Database service '$DbService' is not running."
    }

    $dumpName = "${DbName}_$timestamp.dump"
    $globalsName = "${DbName}_globals_$timestamp.sql"
    $schemaName = "${DbName}_schema_$timestamp.sql"

    $dumpContainer = "/tmp/$dumpName"
    $globalsContainer = "/tmp/$globalsName"
    $schemaContainer = "/tmp/$schemaName"

    $dumpLocal = Join-Path $dbFolder $dumpName
    $globalsLocal = Join-Path $dbFolder $globalsName
    $schemaLocal = Join-Path $dbFolder $schemaName
    $inventoryLocal = Join-Path $dbFolder "database_inventory_$timestamp.txt"

    Write-Host "`n=== POSTGRESQL FULL LOGICAL BACKUP ==="
    docker compose exec -T $DbService pg_dump `
        -U $DbUser `
        -d $DbName `
        --format=custom `
        --compress=6 `
        --no-owner `
        --file=$dumpContainer
    Assert-ExitCode "pg_dump"

    Write-Host "`n=== POSTGRESQL GLOBALS ==="
    docker compose exec -T $DbService pg_dumpall `
        -U $DbUser `
        --globals-only `
        --file=$globalsContainer
    Assert-ExitCode "pg_dumpall --globals-only"

    Write-Host "`n=== POSTGRESQL SCHEMA-ONLY SNAPSHOT ==="
    docker compose exec -T $DbService pg_dump `
        -U $DbUser `
        -d $DbName `
        --schema-only `
        --no-owner `
        --no-privileges `
        --no-tablespaces `
        --file=$schemaContainer
    Assert-ExitCode "pg_dump --schema-only"

    Write-Host "`n=== VALIDATE DATABASE DUMP ==="
    docker compose exec -T $DbService pg_restore --list $dumpContainer | Out-Null
    Assert-ExitCode "pg_restore --list"
    Write-Host "OK - PostgreSQL can read the custom-format dump."

    Write-Host "`n=== COPY DATABASE BACKUPS TO WINDOWS ==="
    docker compose cp "${DbService}:$dumpContainer" $dumpLocal
    Assert-ExitCode "copy database dump"

    docker compose cp "${DbService}:$globalsContainer" $globalsLocal
    Assert-ExitCode "copy globals"

    docker compose cp "${DbService}:$schemaContainer" $schemaLocal
    Assert-ExitCode "copy schema-only snapshot"

    docker compose exec -T $DbService rm -f $dumpContainer $globalsContainer $schemaContainer
    Assert-ExitCode "remove temporary container backup files"

    foreach ($path in @($dumpLocal, $globalsLocal, $schemaLocal)) {
        if (-not (Test-Path $path)) {
            throw "Expected backup file missing: $path"
        }
        if ((Get-Item $path).Length -le 0) {
            throw "Backup file is empty: $path"
        }
    }

    Write-Host "`n=== DATABASE INVENTORY ==="
    $inventorySql = @"
SELECT 'database=' || current_database();
SELECT 'postgres_version=' || current_setting('server_version');
SELECT 'public_tables=' || count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';
SELECT 'suburb_rows=' || count(*) FROM public.locations_suburb;
SELECT 'external_data_files=' || count(*) FROM public.imports_externaldatafile;
"@

    $inventorySql | docker compose exec -T $DbService psql `
        -U $DbUser `
        -d $DbName `
        -X `
        -v ON_ERROR_STOP=1 `
        -At `
        -f - | Set-Content -Path $inventoryLocal -Encoding utf8
    Assert-ExitCode "database inventory"

    Write-Host "`n=== LOCAL GIT BACKUP ==="
    $branch = (git branch --show-current).Trim()
    Assert-ExitCode "git branch --show-current"

    $commit = (git rev-parse HEAD).Trim()
    Assert-ExitCode "git rev-parse HEAD"

    $bundlePath = Join-Path $gitFolder "Freight-Calc-v1.5_$timestamp.bundle"

    git bundle create $bundlePath --all
    Assert-ExitCode "git bundle create"

    git bundle verify $bundlePath
    Assert-ExitCode "git bundle verify"

    Write-Host "`n=== LOCAL GIT RECOVERY BUNDLE ==="
    Write-Host "Branch : $branch"
    Write-Host "Commit : $commit"
    Write-Host "Bundle : $bundlePath"

    Write-Host "`n=== SHA256 CHECKSUMS ==="
    $dumpHash = Get-Sha256 $dumpLocal
    $globalsHash = Get-Sha256 $globalsLocal
    $schemaHash = Get-Sha256 $schemaLocal
    $inventoryHash = Get-Sha256 $inventoryLocal
    $bundleHash = Get-Sha256 $bundlePath

    $checksumsPath = Join-Path $backupFolder "SHA256SUMS.txt"
    @(
        "$dumpHash  postgresql\$dumpName"
        "$globalsHash  postgresql\$globalsName"
        "$schemaHash  postgresql\$schemaName"
        "$inventoryHash  postgresql\$(Split-Path $inventoryLocal -Leaf)"
        "$bundleHash  git\$(Split-Path $bundlePath -Leaf)"
    ) | Set-Content -Path $checksumsPath -Encoding utf8

    Write-Host "`n=== RECOVERY MANIFEST ==="
    $manifestPath = Join-Path $backupFolder "BACKUP_MANIFEST.txt"

    @"
Freight Calculator - Recovery Point
===================================

Created local time : $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
Project root       : $ProjectRoot

POSTGRESQL
----------
Service            : $DbService
Database           : $DbName
Database user      : $DbUser
Full dump          : $dumpLocal
Globals            : $globalsLocal
Schema-only        : $schemaLocal
Inventory          : $inventoryLocal
Dump SHA256        : $dumpHash
Globals SHA256     : $globalsHash
Schema SHA256      : $schemaHash

GIT
---
Branch             : $branch
Commit             : $commit
Git bundle         : $bundlePath
Bundle SHA256      : $bundleHash

SAFETY
------
- PostgreSQL production data was NOT modified.
- This folder is an independent local recovery point.
- Keep a second copy on independent storage when possible.
"@ | Set-Content -Path $manifestPath -Encoding utf8

    Write-Host "`n=== FINAL VALIDATION ==="
    foreach ($path in @($dumpLocal, $globalsLocal, $schemaLocal, $inventoryLocal, $bundlePath, $checksumsPath, $manifestPath)) {
        if (-not (Test-Path $path)) {
            throw "Expected recovery file missing: $path"
        }
        Write-Host "OK: $path"
    }

    if (-not [string]::IsNullOrWhiteSpace($SecondaryCopyPath)) {
        Write-Host "`n=== SECONDARY COPY ==="
        if (-not (Test-Path $SecondaryCopyPath)) {
            New-Item -ItemType Directory -Force -Path $SecondaryCopyPath | Out-Null
        }

        $secondaryFolder = Join-Path $SecondaryCopyPath (Split-Path $backupFolder -Leaf)
        Copy-Item -Path $backupFolder -Destination $secondaryFolder -Recurse -Force
        Write-Host "Secondary recovery copy created at:"
        Write-Host $secondaryFolder
    }

    Write-Host "`n=== BACKUP COMPLETED SUCCESSFULLY ==="
    Write-Host "Recovery point : $backupFolder"
    Write-Host "Production DB  : NOT MODIFIED"
}
finally {
    Stop-Transcript | Out-Null
}

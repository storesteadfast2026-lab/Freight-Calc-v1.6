[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$DumpPath,

    [string]$ProjectRoot = "C:\Docker-Projects\Freight-Calc-v1.5",
    [string]$BackupRoot = "C:\Docker-Backups\Freight-Calc",
    [string]$DbService = "db",
    [string]$WebService = "web",
    [string]$DbName = "freight_platform",
    [string]$DbUser = "freight_user"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-ExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path $DumpPath)) {
    throw "Dump file not found: $DumpPath"
}
if (-not (Test-Path $ProjectRoot)) {
    throw "Project root does not exist: $ProjectRoot"
}

Set-Location $ProjectRoot

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$restoreDb = "${DbName}_restore_$timestamp"
$previousDb = "${DbName}_pre_restore_$timestamp"
$failedDb = "${DbName}_failed_restore_$timestamp"
$dumpLeaf = Split-Path $DumpPath -Leaf
$dumpContainer = "/tmp/$dumpLeaf"

$emergencyFolder = Join-Path $BackupRoot "pre_restore_$timestamp"
New-Item -ItemType Directory -Force -Path $emergencyFolder | Out-Null

Write-Host "============================================================"
Write-Host " PRODUCTION POSTGRESQL RESTORE"
Write-Host "============================================================"
Write-Host ""
Write-Host "WARNING: THIS OPERATION CHANGES THE PRODUCTION DATABASE."
Write-Host ""
Write-Host "Production DB : $DbName"
Write-Host "Restore dump  : $DumpPath"
Write-Host ""
Write-Host "Safety sequence:"
Write-Host "  1. Validate requested dump."
Write-Host "  2. Back up current production."
Write-Host "  3. Restore into a NEW isolated database."
Write-Host "  4. Validate isolated restore."
Write-Host "  5. Stop Django web service."
Write-Host "  6. Rename current DB instead of deleting it."
Write-Host "  7. Promote restored DB."
Write-Host "  8. Restart Django and run database-aware check."
Write-Host "  9. Attempt automatic rollback if post-swap check fails."
Write-Host ""

$expected = "RESTORE $DbName"
$confirmation = Read-Host "Type exactly '$expected' to continue"

if ($confirmation -cne $expected) {
    Write-Host "Restore cancelled. Nothing was changed."
    exit 2
}

$webStopped = $false
$swapCompleted = $false
$restoreDbCreated = $false

try {
    Write-Host "`n=== VALIDATE REQUESTED BACKUP ==="
    docker compose cp $DumpPath "${DbService}:$dumpContainer"
    Assert-ExitCode "copy requested dump"

    docker compose exec -T $DbService pg_restore --list $dumpContainer | Out-Null
    Assert-ExitCode "pg_restore --list"

    Write-Host "`n=== EMERGENCY BACKUP OF CURRENT PRODUCTION ==="
    $emergencyName = "${DbName}_pre_restore_$timestamp.dump"
    $emergencyContainer = "/tmp/$emergencyName"
    $emergencyLocal = Join-Path $emergencyFolder $emergencyName

    docker compose exec -T $DbService pg_dump `
        -U $DbUser `
        -d $DbName `
        --format=custom `
        --compress=6 `
        --no-owner `
        --file=$emergencyContainer
    Assert-ExitCode "emergency pg_dump"

    docker compose exec -T $DbService pg_restore --list $emergencyContainer | Out-Null
    Assert-ExitCode "validate emergency backup"

    docker compose cp "${DbService}:$emergencyContainer" $emergencyLocal
    Assert-ExitCode "copy emergency backup"

    $emergencyHash = (Get-FileHash -Path $emergencyLocal -Algorithm SHA256).Hash.ToLowerInvariant()

    @"
Emergency pre-restore backup
============================
Created        : $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
Database       : $DbName
Dump           : $emergencyLocal
SHA256         : $emergencyHash
Requested dump : $DumpPath
"@ | Set-Content -Path (Join-Path $emergencyFolder "PRE_RESTORE_MANIFEST.txt") -Encoding utf8

    docker compose exec -T $DbService rm -f $emergencyContainer
    Assert-ExitCode "remove emergency container dump"

    Write-Host "Emergency backup: $emergencyLocal"

    Write-Host "`n=== CREATE ISOLATED RESTORE DATABASE ==="
    docker compose exec -T $DbService createdb -U $DbUser -O $DbUser $restoreDb
    Assert-ExitCode "create isolated restore database"
    $restoreDbCreated = $true

    Write-Host "`n=== RESTORE INTO ISOLATED DATABASE ==="
    docker compose exec -T $DbService pg_restore `
        -U $DbUser `
        -d $restoreDb `
        --no-owner `
        --exit-on-error `
        $dumpContainer
    Assert-ExitCode "restore isolated database"

    Write-Host "`n=== VALIDATE ISOLATED RESTORE ==="
    $validationSql = @"
SELECT 'database=' || current_database();
SELECT 'public_tables=' || count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';
SELECT 'suburb_rows=' || count(*) FROM public.locations_suburb;
SELECT 'external_data_files=' || count(*) FROM public.imports_externaldatafile;
"@

    $validationSql | docker compose exec -T $DbService psql `
        -U $DbUser `
        -d $restoreDb `
        -X `
        -v ON_ERROR_STOP=1 `
        -At `
        -f -
    Assert-ExitCode "isolated restore validation"

    Write-Host "`n=== STOP DJANGO WEB SERVICE ==="
    docker compose stop $WebService
    Assert-ExitCode "stop web service"
    $webStopped = $true

    Write-Host "`n=== TERMINATE DATABASE CONNECTIONS ==="
    docker compose exec -T $DbService psql `
        -U $DbUser `
        -d postgres `
        -v ON_ERROR_STOP=1 `
        -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DbName','$restoreDb') AND pid <> pg_backend_pid();" | Out-Null
    Assert-ExitCode "terminate database connections"

    Write-Host "`n=== SAFE DATABASE SWAP ==="
    docker compose exec -T $DbService psql `
        -U $DbUser `
        -d postgres `
        -v ON_ERROR_STOP=1 `
        -c "ALTER DATABASE $DbName RENAME TO $previousDb;"
    Assert-ExitCode "rename current production database"

    docker compose exec -T $DbService psql `
        -U $DbUser `
        -d postgres `
        -v ON_ERROR_STOP=1 `
        -c "ALTER DATABASE $restoreDb RENAME TO $DbName;"
    Assert-ExitCode "promote restored database"

    $swapCompleted = $true

    Write-Host "`n=== START DJANGO WEB SERVICE ==="
    docker compose start $WebService
    Assert-ExitCode "start web service"
    $webStopped = $false

    Start-Sleep -Seconds 3

    Write-Host "`n=== DJANGO POST-RESTORE CHECK ==="
    docker compose exec -T $WebService python manage.py check --database default
    Assert-ExitCode "Django database-aware system check"

    Write-Host "`n=== PRODUCTION RESTORE COMPLETED ==="
    Write-Host "Active DB        : $DbName"
    Write-Host "Previous DB kept : $previousDb"
    Write-Host "Emergency backup : $emergencyLocal"
    Write-Host ""
    Write-Host "Do not delete '$previousDb' until functional validation"
    Write-Host "and a fresh post-restore backup are complete."
}
catch {
    Write-Host "`nERROR: $($_.Exception.Message)"

    if ($swapCompleted) {
        Write-Host "`n=== ATTEMPT AUTOMATIC DATABASE ROLLBACK ==="
        try {
            if (-not $webStopped) {
                docker compose stop $WebService | Out-Null
                $webStopped = $true
            }

            docker compose exec -T $DbService psql `
                -U $DbUser `
                -d postgres `
                -v ON_ERROR_STOP=1 `
                -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DbName','$previousDb') AND pid <> pg_backend_pid();" | Out-Null

            docker compose exec -T $DbService psql `
                -U $DbUser `
                -d postgres `
                -v ON_ERROR_STOP=1 `
                -c "ALTER DATABASE $DbName RENAME TO $failedDb;"
            Assert-ExitCode "rename failed restored DB"

            docker compose exec -T $DbService psql `
                -U $DbUser `
                -d postgres `
                -v ON_ERROR_STOP=1 `
                -c "ALTER DATABASE $previousDb RENAME TO $DbName;"
            Assert-ExitCode "restore original production DB name"

            docker compose start $WebService | Out-Null
            $webStopped = $false

            Write-Host "Automatic rollback completed."
            Write-Host "Original production DB restored as '$DbName'."
            Write-Host "Failed restored DB retained as '$failedDb'."
        }
        catch {
            Write-Host "CRITICAL: automatic rollback also encountered an error."
            Write-Host "Do not make additional changes until PostgreSQL DB names are inspected."
        }
    }
    elseif ($webStopped) {
        try {
            docker compose start $WebService | Out-Null
            $webStopped = $false
        }
        catch {
            Write-Host "WARNING: web service could not be restarted automatically."
        }
    }
    elseif ($restoreDbCreated) {
        Write-Host "Production was not swapped. Current production remains unchanged."
    }

    throw
}
finally {
    docker compose exec -T $DbService rm -f $dumpContainer 2>$null | Out-Null
}

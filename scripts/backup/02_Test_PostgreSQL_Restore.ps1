[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$DumpPath,

    [string]$ProjectRoot = "C:\Docker-Projects\Freight-Calc-v1.5",
    [string]$DbService = "db",
    [string]$DbUser = "freight_user",
    [string]$LogRoot = "C:\Docker-Backups\Freight-Calc\restore_test_logs",
    [switch]$KeepTestDatabase
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory=$true)]
        [scriptblock]$Command,
        [Parameter(Mandatory=$true)]
        [string]$Step
    )

    $previous = $ErrorActionPreference
    try {
        # Docker/Git frequently write normal progress messages to STDERR.
        # Under Windows PowerShell + outer redirection/tee, those messages can
        # become NativeCommandError even when the native exit code is 0.
        $ErrorActionPreference = "Continue"
        & $Command
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }

    if ($exitCode -ne 0) {
        throw "$Step failed with exit code $exitCode."
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
$testDb = "freight_platform_restoretest_$timestamp"
$dumpLeaf = Split-Path $DumpPath -Leaf
$dumpContainer = "/tmp/$dumpLeaf"
$createdTestDb = $false

New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$logPath = Join-Path $LogRoot "02_Test_PostgreSQL_Restore_$timestamp.log"
Start-Transcript -Path $logPath -Force | Out-Null

try {
    Write-Host "============================================================"
    Write-Host " SAFE POSTGRESQL RESTORE TEST"
    Write-Host "============================================================"
    Write-Host "Dump          : $DumpPath"
    Write-Host "Temporary DB  : $testDb"
    Write-Host "Production DB : WILL NOT BE MODIFIED"
    Write-Host "Log           : $logPath"

    Write-Host "`n=== COPY DUMP INTO DATABASE CONTAINER ==="
    Invoke-NativeChecked -Step "copy dump into database container" -Command {
        docker compose cp $DumpPath "${DbService}:$dumpContainer"
    }

    Write-Host "`n=== VALIDATE DUMP CATALOG ==="
    Invoke-NativeChecked -Step "pg_restore --list" -Command {
        docker compose exec -T $DbService pg_restore --list $dumpContainer | Out-Null
    }

    Write-Host "`n=== CREATE TEMPORARY DATABASE ==="
    Invoke-NativeChecked -Step "createdb" -Command {
        docker compose exec -T $DbService createdb -U $DbUser -O $DbUser $testDb
    }
    $createdTestDb = $true

    Write-Host "`n=== RESTORE INTO TEMPORARY DATABASE ==="
    Invoke-NativeChecked -Step "pg_restore" -Command {
        docker compose exec -T $DbService pg_restore `
            -U $DbUser `
            -d $testDb `
            --no-owner `
            --exit-on-error `
            $dumpContainer
    }

    Write-Host "`n=== DATABASE VALIDATION ==="
    $validationSql = @"
SELECT 'database=' || current_database();
SELECT 'public_tables=' || count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';
SELECT 'suburb_rows=' || count(*) FROM public.locations_suburb;
SELECT 'external_data_files=' || count(*) FROM public.imports_externaldatafile;
"@

    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $validationSql | docker compose exec -T $DbService psql `
            -U $DbUser `
            -d $testDb `
            -X `
            -v ON_ERROR_STOP=1 `
            -At `
            -f -
        $validationExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }

    if ($validationExitCode -ne 0) {
        throw "restore validation SQL failed with exit code $validationExitCode."
    }

    Write-Host "`n=== SECONDARY DUMP CHECK ==="
    $verificationDump = "/tmp/${testDb}_verification.dump"

    Invoke-NativeChecked -Step "verification pg_dump" -Command {
        docker compose exec -T $DbService pg_dump `
            -U $DbUser `
            -d $testDb `
            --format=custom `
            --no-owner `
            --file=$verificationDump
    }

    Invoke-NativeChecked -Step "verification pg_restore --list" -Command {
        docker compose exec -T $DbService pg_restore --list $verificationDump | Out-Null
    }

    Invoke-NativeChecked -Step "remove verification dump" -Command {
        docker compose exec -T $DbService rm -f $verificationDump
    }

    Write-Host "`n=== RESTORE TEST PASSED ==="
    Write-Host "The dump restored successfully into an isolated database."
    Write-Host "Production database was NOT modified."
}
finally {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    docker compose exec -T $DbService rm -f $dumpContainer 2>$null | Out-Null

    if ($createdTestDb -and -not $KeepTestDatabase) {
        Write-Host "`n=== CLEANUP TEMPORARY DATABASE ==="

        docker compose exec -T $DbService psql `
            -U $DbUser `
            -d postgres `
            -v ON_ERROR_STOP=1 `
            -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$testDb' AND pid <> pg_backend_pid();" | Out-Null

        docker compose exec -T $DbService dropdb -U $DbUser --if-exists $testDb | Out-Null
        Write-Host "Temporary restore database removed."
    }
    elseif ($createdTestDb -and $KeepTestDatabase) {
        Write-Host "Test database retained: $testDb"
    }

    $ErrorActionPreference = $previous
    Stop-Transcript | Out-Null
}

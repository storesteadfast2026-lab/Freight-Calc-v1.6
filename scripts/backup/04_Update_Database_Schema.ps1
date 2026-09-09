[CmdletBinding()]
param(
    [string]$ProjectRoot = "C:\Docker-Projects\Freight-Calc-v1.5",
    [string]$DbService = "db",
    [string]$DbName = "freight_platform",
    [string]$DbUser = "freight_user",
    [switch]$SkipRestoreValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-ExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path $ProjectRoot)) {
    throw "Project root does not exist: $ProjectRoot"
}

Set-Location $ProjectRoot

$schemaDir = Join-Path $ProjectRoot "database"
$schemaFile = Join-Path $schemaDir "schema.sql"
$tempSchemaFile = Join-Path $schemaDir "schema.new.sql"
$containerSchema = "/tmp/${DbName}_schema.sql"

New-Item -ItemType Directory -Force -Path $schemaDir | Out-Null

Write-Host "============================================================"
Write-Host " UPDATE VERSIONED DATABASE SCHEMA"
Write-Host "============================================================"
Write-Host "Output  : $schemaFile"
Write-Host "Data    : NOT EXPORTED"
Write-Host "Git     : file is NOT staged or committed automatically"

Write-Host "`n=== EXPORT SCHEMA ONLY ==="
docker compose exec -T $DbService pg_dump `
    -U $DbUser `
    -d $DbName `
    --schema-only `
    --no-owner `
    --no-privileges `
    --no-tablespaces `
    --file=$containerSchema
Assert-ExitCode "pg_dump --schema-only"

docker compose cp "${DbService}:$containerSchema" $tempSchemaFile
Assert-ExitCode "copy schema"

docker compose exec -T $DbService rm -f $containerSchema
Assert-ExitCode "remove temporary schema"

if (-not (Test-Path $tempSchemaFile)) {
    throw "Schema export file was not created."
}
if ((Get-Item $tempSchemaFile).Length -le 0) {
    throw "Schema export is empty."
}

if (-not $SkipRestoreValidation) {
    Write-Host "`n=== VALIDATE SCHEMA BY REBUILDING TEMP DATABASE ==="

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $testDb = "${DbName}_schematest_$timestamp"
    $testContainerSchema = "/tmp/schema_test_$timestamp.sql"
    $testDbCreated = $false

    try {
        docker compose cp $tempSchemaFile "${DbService}:$testContainerSchema"
        Assert-ExitCode "copy schema for validation"

        docker compose exec -T $DbService createdb -U $DbUser -O $DbUser $testDb
        Assert-ExitCode "create schema test database"
        $testDbCreated = $true

        docker compose exec -T $DbService psql `
            -U $DbUser `
            -d $testDb `
            -X `
            -v ON_ERROR_STOP=1 `
            -f $testContainerSchema | Out-Null
        Assert-ExitCode "apply schema to test database"

        $tableCount = (docker compose exec -T $DbService psql `
            -U $DbUser `
            -d $testDb `
            -X `
            -At `
            -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';").Trim()
        Assert-ExitCode "count restored schema tables"

        Write-Host "OK - Schema rebuilt successfully."
        Write-Host "Public tables in test DB: $tableCount"
    }
    finally {
        docker compose exec -T $DbService rm -f $testContainerSchema 2>$null | Out-Null

        if ($testDbCreated) {
            docker compose exec -T $DbService psql `
                -U $DbUser `
                -d postgres `
                -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$testDb' AND pid <> pg_backend_pid();" | Out-Null

            docker compose exec -T $DbService dropdb -U $DbUser --if-exists $testDb | Out-Null
        }
    }
}

Write-Host "`n=== INSTALL VERSIONED SCHEMA FILE ==="
Move-Item -Path $tempSchemaFile -Destination $schemaFile -Force

$hash = (Get-FileHash $schemaFile -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host "Schema : $schemaFile"
Write-Host "SHA256 : $hash"

Write-Host "`n=== GIT STATUS FOR SCHEMA ==="
git status --short -- database/schema.sql
Assert-ExitCode "git status schema"

Write-Host "`n=== GIT DIFF FOR SCHEMA ==="
git diff -- database/schema.sql
Assert-ExitCode "git diff schema"

Write-Host "`n=== COMPLETE ==="
Write-Host "database/schema.sql is ready for review/versioning."
Write-Host "No PostgreSQL data was exported."
Write-Host "Nothing was staged or committed automatically."

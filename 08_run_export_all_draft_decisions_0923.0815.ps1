# Work.Calc - Script 08 runner
# Run from: C:\Docker-Projects\Freight-Calc-v1.6
# READ ONLY

$ErrorActionPreference = "Stop"

$ScriptFile = ".\08_export_all_draft_decisions_0923.0815.py"
$ContainerCsv = "/tmp/draft_decisions_229_0923.0815.csv"
$ContainerDiag = "/tmp/draft_decision_diagnostics_0923.0815.txt"
$LocalCsv = ".\draft_decisions_229_0923.0815.csv"
$LocalDiag = ".\draft_decision_diagnostics_0923.0815.txt"

if (-not (Test-Path $ScriptFile)) {
    Write-Host "ERROR: $ScriptFile not found in the current folder." -ForegroundColor Red
    exit 1
}

Write-Host "Exporting Work.Calc draft decisions (READ ONLY)..." -ForegroundColor Cyan

Get-Content $ScriptFile -Raw | docker compose exec -T web python manage.py shell

if ($LASTEXITCODE -ne 0) {
    Write-Host "Export failed. No database changes were made by this script." -ForegroundColor Red
    exit $LASTEXITCODE
}

$ContainerId = (docker compose ps -q web).Trim()
if (-not $ContainerId) {
    Write-Host "ERROR: web container not found." -ForegroundColor Red
    exit 1
}

docker cp "${ContainerId}:${ContainerCsv}" $LocalCsv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker cp "${ContainerId}:${ContainerDiag}" $LocalDiag
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done. No database changes were made." -ForegroundColor Green
Write-Host "CSV: $LocalCsv"
Write-Host "Diagnostics: $LocalDiag"

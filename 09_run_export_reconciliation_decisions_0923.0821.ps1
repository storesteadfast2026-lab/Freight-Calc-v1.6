# Work.Calc - Script 09 runner
# Run from C:\Docker-Projects\Freight-Calc-v1.6

$ErrorActionPreference = "Stop"

$ScriptFile = ".\09_export_reconciliation_decisions_0923.0821.py"
$ContainerCsv = "/tmp/reconciliation_decisions_0923.0821.csv"
$ContainerSummary = "/tmp/reconciliation_decisions_summary_0923.0821.txt"

$LocalCsv = ".\reconciliation_decisions_0923.0821.csv"
$LocalSummary = ".\reconciliation_decisions_summary_0923.0821.txt"

if (-not (Test-Path $ScriptFile)) {
    Write-Host "ERROR: $ScriptFile not found." -ForegroundColor Red
    exit 1
}

Write-Host "Exporting reconciliation decisions (READ ONLY)..." -ForegroundColor Cyan

Get-Content $ScriptFile -Raw |
    docker compose exec -T web python manage.py shell

if ($LASTEXITCODE -ne 0) {
    Write-Host "Export failed. No database changes were made." -ForegroundColor Red
    exit $LASTEXITCODE
}

$ContainerId = (docker compose ps -q web).Trim()

if (-not $ContainerId) {
    Write-Host "ERROR: web container not found." -ForegroundColor Red
    exit 1
}

docker cp "${ContainerId}:${ContainerCsv}" $LocalCsv
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR copying CSV." -ForegroundColor Red
    exit $LASTEXITCODE
}

docker cp "${ContainerId}:${ContainerSummary}" $LocalSummary
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR copying summary." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Done. No database changes were made." -ForegroundColor Green
Write-Host "CSV: $LocalCsv"
Write-Host "Summary: $LocalSummary"

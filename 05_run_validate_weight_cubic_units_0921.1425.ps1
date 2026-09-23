# Work.Calc - Script 05 runner
# Run from C:\Docker-Projects\Freight-Calc-v1.6

$ErrorActionPreference = "Stop"
$Script = ".\05_validate_weight_cubic_units_0921.1425.py"

if (-not (Test-Path $Script)) {
    Write-Host "ERROR: $Script not found." -ForegroundColor Red
    exit 1
}

Get-Content $Script -Raw | docker compose exec -T web python manage.py shell

if ($LASTEXITCODE -ne 0) {
    Write-Host "Validation failed. The validation script is read-only." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Validation completed. No database changes were made." -ForegroundColor Green

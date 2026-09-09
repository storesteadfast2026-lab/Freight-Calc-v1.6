# Validation Runbook

## Prerequisites

From PowerShell:

```powershell
cd C:\Docker-Projects\Freight-Calc-05jun
.\.venv-excel\Scripts\activate
```

Docker must be running:

```powershell
docker compose ps
```

## Generate Excel expected outputs from the official workbook

Example for a temporary real check:

```powershell
Remove-Item .\generated_excel_baselines\live_real_check -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\app\apps\freight\fixtures\live_real_check -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\sample_data\live_baselines\live_real_check -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\reports\live_real_check -Recurse -Force -ErrorAction SilentlyContinue

mkdir .\generated_excel_baselines\live_real_check -Force
mkdir .\app\apps\freight\fixtures\live_real_check -Force
mkdir .\sample_data\live_baselines\live_real_check -Force
mkdir .\reports\live_real_check -Force

python .\tools\excel\generate_excel_expected_outputs.py --workbook .\sample_data\V2026.R2_Unlocked_STH_Freight_Calculator.xlsx --cases .\app\apps\freight\fixtures\live_latest\sth_excel_generated_cases.csv --output-dir .\generated_excel_baselines\live_real_check --refresh --save-workbook
```

## Copy generated files to a Docker-visible location

```powershell
Copy-Item .\generated_excel_baselines\live_real_check\sth_excel_generated_cases.csv .\app\apps\freight\fixtures\live_real_check\sth_excel_generated_cases.csv -Force
Copy-Item .\generated_excel_baselines\live_real_check\sth_excel_generated_outputs.csv .\app\apps\freight\fixtures\live_real_check\sth_excel_generated_outputs.csv -Force
Copy-Item .\generated_excel_baselines\live_real_check\sth_excel_generated_components.csv .\app\apps\freight\fixtures\live_real_check\sth_excel_generated_components.csv -Force

$baseline = Get-ChildItem .\generated_excel_baselines\live_real_check -Filter "STH_LIVE_BASELINE_*.xlsx" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item $baseline.FullName .\sample_data\live_baselines\live_real_check\ -Force
$baselineName = $baseline.Name
$baselineName
```

## Validate Django against the generated Excel baseline

```powershell
docker compose exec web python manage.py validate_excel_battery --import-workbook --workbook /app/sample_data/live_baselines/live_real_check/$baselineName --replace --cases /app/apps/freight/fixtures/live_real_check/sth_excel_generated_cases.csv --expected /app/apps/freight/fixtures/live_real_check/sth_excel_generated_outputs.csv --components /app/apps/freight/fixtures/live_real_check/sth_excel_generated_components.csv --report /app/reports/live_real_check/sth_excel_live_real_check_report.csv
```

Summary:

```powershell
Import-Csv .\reports\live_real_check\sth_excel_live_real_check_report.csv | Group-Object row_type,overall_status | Format-Table Count, Name
```

Failure details:

```powershell
Import-Csv .\reports\live_real_check\sth_excel_live_real_check_report.csv | Where-Object { $_.overall_status -eq "FAIL" } | Select-Object row_type,case_id,rank,expected_carrier,actual_carrier,expected_service,actual_service,expected_estimate_ex_gst,actual_estimate_ex_gst,difference,notes | Format-Table -Auto
```

## Current validated results

### live_latest

```text
Cases run: 20
Expected output rows loaded: 77
Report rows: 97
OK rows: 97
FAIL rows: 0
```

### random_current 15 cases

```text
Cases run: 15
Expected output rows loaded: 21
Report rows: 36
OK rows: 36
FAIL rows: 0
```

## Important operational rule

When switching between batteries, import the matching baseline first or use `--import-workbook` in the validation command.

Avoid this situation:

```text
live_latest CSVs + random_current PostgreSQL data
random_current CSVs + live_latest PostgreSQL data
```

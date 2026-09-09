# Validation Runbook

## Prerequisites

From PowerShell:

```powershell
cd C:\Docker-Projects\Freight-Calc-Nuevo
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

### random_current

A previous documented run recorded 15 cases and 36 OK rows. The 2026-07-28 review package does not contain the complete matching evidence set, so the current random status must be treated as not confirmed until regenerated. The package currently has 5 input cases only.

## Regenerate random_current using fixed paths and names

Do not create `random_5`, `random_10`, `random_30` or other count-based folders. Replace the contents of the fixed workspace only after preserving any evidence that must be retained elsewhere.

```powershell
New-Item .\generated_excel_baselines\random_current -ItemType Directory -Force | Out-Null
New-Item .\app\apps\freight\fixtures\random_current -ItemType Directory -Force | Out-Null
New-Item .\sample_data\live_baselines\random_current -ItemType Directory -Force | Out-Null
New-Item .\reports\random_current -ItemType Directory -Force | Out-Null

python .\tools\excel\generate_excel_expected_outputs.py `
  --workbook .\sample_data\V2026.R2_Unlocked_STH_Freight_Calculator.xlsx `
  --cases .\app\apps\freight\fixtures\random_current\sth_excel_random_cases.csv `
  --output-dir .\generated_excel_baselines\random_current `
  --refresh `
  --save-workbook

Copy-Item .\generated_excel_baselines\random_current\sth_excel_generated_cases.csv .\app\apps\freight\fixtures\random_current\sth_excel_random_cases.csv -Force
Copy-Item .\generated_excel_baselines\random_current\sth_excel_generated_outputs.csv .\app\apps\freight\fixtures\random_current\sth_excel_random_outputs.csv -Force
Copy-Item .\generated_excel_baselines\random_current\sth_excel_generated_components.csv .\app\apps\freight\fixtures\random_current\sth_excel_random_components.csv -Force

$randomBaseline = Get-ChildItem .\generated_excel_baselines\random_current -Filter "STH_LIVE_BASELINE_*.xlsx" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item $randomBaseline.FullName .\sample_data\live_baselines\random_current\ -Force
$randomBaselineName = $randomBaseline.Name

docker compose exec web python manage.py validate_excel_battery `
  --import-workbook `
  --workbook /app/sample_data/live_baselines/random_current/$randomBaselineName `
  --replace `
  --cases /app/apps/freight/fixtures/random_current/sth_excel_random_cases.csv `
  --expected /app/apps/freight/fixtures/random_current/sth_excel_random_outputs.csv `
  --components /app/apps/freight/fixtures/random_current/sth_excel_random_components.csv `
  --report /app/reports/random_current/sth_excel_random_comparison_report.csv
```

After the command, confirm the four fixed CSV files and the matching baseline are present before recording the result in `docs/12_validation_findings_log.md`.

## Important operational rule

When switching between batteries, import the matching baseline first or use `--import-workbook` in the validation command.

Avoid this situation:

```text
live_latest CSVs + random_current PostgreSQL data
random_current CSVs + live_latest PostgreSQL data
```

## Fuel handling during Excel-vs-Django validation

Historical baselines must use the fuel cached in the same workbook that generated the expected CSVs. `validate_excel_battery --import-workbook` now imports with:

```text
--fuel-source workbook
```

After a normally completed validation, the command reapplies the active Admin fuel dataset.

If the validation is interrupted, restore it manually:

```powershell
docker compose exec web python manage.py reapply_active_fuel --client STH
```

For operational checks, confirm the source in Admin:

```text
Carriers → Client carrier configs → Fuel levy source
```


## Validate Cubic Margin

Run the dedicated application-rule tests:

```powershell
docker compose exec web python manage.py test apps.freight.tests.test_cubic_margin -v 2
```

Expected test discovery from the current source:

```text
Found 7 test(s)
```

Record the actual `OK` result; do not infer it solely from source inspection. Then run the standard 0% Excel-vs-Django battery to confirm that default behavior remains unchanged.

## Validate the calculator visual-only refresh

Confirm that no schema change was introduced:

```powershell
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run
```

Run the calculator DOM-contract, access and calculation regressions:

```powershell
docker compose exec web python manage.py test `
  apps.freight `
  apps.authentication_gateway.tests.test_login_flow `
  --noinput `
  -v 2
```

The visual-contract tests confirm that required IDs appear exactly once, the
existing actions and `/api/calculate/` remain present, and no saved-shipment or
staged progress control was introduced.

Manual browser verification:

1. Sign in as a Customer and as an Internal User.
2. Confirm client selection visibility remains appropriate.
3. Open suburb and product dropdowns without typing.
4. Add and remove shipment rows; confirm Items, weight and cubic update.
5. Enter Cubic Margin values 0, 10, 20 and an invalid value.
6. Run a known calculation and compare carrier, service and estimate with the
   pre-refresh result.
7. Check desktop, tablet and mobile widths.
8. Confirm the login page visual remains unchanged.

## Validate the three Django Admin source modules

### Validate Product Admin visibility

```powershell
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations products --check --dry-run
docker compose exec web python manage.py test apps.products.tests.test_admin_visibility -v 2
```

Expected result:

```text
Found 2 test(s)
OK
```

Confirm manually that `Products > Products` remains visible and
`Products > Product kit components` is absent.

### Migration and system check

```powershell
docker compose exec web python manage.py showmigrations imports
docker compose exec web python manage.py check
```

Expected Product/Stock migration:

```text
[X] 0003_product_stock_reference_sources
```

### Targeted import tests

```powershell
docker compose exec web python manage.py test apps.imports.tests.test_fuel_import apps.imports.tests.test_product_stock_sources -v 2
```

The current code contains 12 targeted import tests: 6 Fuel and 6 Product/Stock tests. Record the actual run result; do not claim success from test count alone.

### Confirm operational isolation

Run before and after Product/Stock uploads:

```powershell
docker compose exec web python manage.py shell -c "from apps.products.models import Product; from apps.rates.models import FreightRate,FreightZone; from apps.carriers.models import ClientCarrierConfig; print({'products':Product.objects.count(),'rates':FreightRate.objects.count(),'zones':FreightZone.objects.count(),'configs':ClientCarrierConfig.objects.count()})"
```

The four counts must remain unchanged.

### Confirm reference rows and files

```powershell
docker compose exec web python manage.py shell -c "from apps.imports.models import ExternalDataFile,ProductSourceRow,StockSourceRow; print({'external_files':ExternalDataFile.objects.count(),'product_source_rows':ProductSourceRow.objects.count(),'stock_source_rows':StockSourceRow.objects.count()})"
```

### Current review-package limitation

The 2026-07-28 review package reported `manage.py check` and migrations successfully, but its complete test-suite capture stopped while creating the test database and its database-summary command was malformed. Re-run the commands above in the project environment before treating the runtime state as fully verified.

## User-access implementation validation order

When user code is authorized, validate in this order:

```text
1. model/profile validation tests
2. login/logout and inactive-user tests
3. customer client-isolation tests
4. internal selected/all-client tests
5. Admin custom-action permission tests
6. interactive password setup tests; email invitation/reset delivery remains pending
7. existing freight and import regression tests
8. Excel-vs-Django batteries to prove calculation behavior is unchanged
```

## User access deployment and validation — 2026-07-22

Apply migrations and createte the minimum administrator group:

```powershell
cd C:\Docker-Projects\Freight-Calc-Nuevo

docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py setup_access_roles
docker compose exec web python manage.py check
```

Run the stable access modules affected by group-based administration:

```powershell
docker compose exec web python manage.py test `
  apps.authentication_gateway.tests.test_access `
  apps.authentication_gateway.tests.test_admin_access `
  apps.authentication_gateway.tests.test_commands `
  apps.authentication_gateway.tests.test_login_flow `
  apps.authentication_gateway.tests.test_user_admin_integration `
  -v 2
```

Expected current result:

```text
Found 28 test(s)
OK
```

Then run the affected regressions:

```powershell
docker compose exec web python manage.py test apps.freight apps.imports apps.clients -v 2
```

Expected current result:

```text
Found 31 test(s)
OK
```

The complete `apps.authentication_gateway` suite currently has four known
baseline failures in `test_login_security`: the expected generic message does
not match the current login form. They are not caused by group-based access and
must be resolved as a separate login-security change.

Create a local test Customer User:

```powershell
docker compose exec -it web python manage.py create_calculator_user `
  --email customer@example.com `
  --role customer `
  --client STH `
  --set-password
```

Create a local test Administrator:

```powershell
docker compose exec -it web python manage.py create_calculator_user `
  --email admin@example.com `
  --role internal `
  --all-clients `
  --django-admin `
  --set-password
```

After authentication tests pass, rerun the fixed Excel-vs-Django baseline. User access changes are released only when both access tests and freight regression validation pass.

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

## Mandatory isolated PostgreSQL database

Never execute an Excel battery with `--import-workbook --replace` against the
operational database. The import deletes and rebuilds calculation data and
removes non-Fuel Product/Stock import history for the selected client.

Create a uniquely named validation database in the existing PostgreSQL
container:

```powershell
$ValidationDb = "freight_validation_$((Get-Date).ToString('yyyyMMdd_HHmmss'))"

docker compose exec -T db sh -lc `
  'createdb --username="$POSTGRES_USER" "$1"' sh $ValidationDb

docker compose run --rm --no-deps `
  --env "POSTGRES_DB=$ValidationDb" `
  web python manage.py migrate --noinput
```

Every battery command in this runbook uses `docker compose run` with that
database. Do not replace it with `docker compose exec web`, because `exec web`
uses the operational database configured for the running application.

For the currently retained `live_latest_refresh` evidence, first verify the
baseline path in the full repository. The 2026-08-18 review ZIP does not
include this file:

```powershell
$LiveBaselineRelative = `
  "live_latest_refresh/STH_LIVE_BASELINE_20260714_152158.xlsx"
$LiveBaselineHost = Join-Path `
  ".\sample_data\live_baselines" `
  $LiveBaselineRelative

if (-not (Test-Path $LiveBaselineHost -PathType Leaf)) {
    throw "Matching live_latest baseline not found: $LiveBaselineHost"
}

Get-FileHash $LiveBaselineHost -Algorithm SHA256

$LiveEvidenceFiles = @(
    $LiveBaselineHost,
    ".\app\apps\freight\fixtures\live_latest\sth_excel_generated_cases.csv",
    ".\app\apps\freight\fixtures\live_latest\sth_excel_generated_outputs.csv",
    ".\app\apps\freight\fixtures\live_latest\sth_excel_generated_components.csv"
)

$LiveEvidenceFiles |
    ForEach-Object { Get-FileHash $_ -Algorithm SHA256 } |
    Select-Object Path, Hash |
    Export-Csv `
      ".\reports\sth_excel_live_latest_manifest.csv" `
      -NoTypeInformation
```

The filename alone is not permanent proof of pairing. Preserve its SHA-256
together with the three fixture hashes whenever the baseline is refreshed.

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
docker compose run --rm --no-deps `
  --env "POSTGRES_DB=$ValidationDb" `
  web python manage.py validate_excel_battery `
  --import-workbook `
  --workbook "/app/sample_data/live_baselines/live_real_check/$baselineName" `
  --replace `
  --cases /app/apps/freight/fixtures/live_real_check/sth_excel_generated_cases.csv `
  --expected /app/apps/freight/fixtures/live_real_check/sth_excel_generated_outputs.csv `
  --components /app/apps/freight/fixtures/live_real_check/sth_excel_generated_components.csv `
  --report /app/reports/live_real_check/sth_excel_live_real_check_report.csv `
  --fail-on-difference
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

A previous documented run recorded 15 cases and 36 OK rows. The 2026-08-18 review package does not contain the complete matching evidence set, so the current random status must be treated as not confirmed until regenerated. The package currently has 5 input cases only.

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

docker compose run --rm --no-deps `
  --env "POSTGRES_DB=$ValidationDb" `
  web python manage.py validate_excel_battery `
  --import-workbook `
  --workbook /app/sample_data/live_baselines/random_current/$randomBaselineName `
  --replace `
  --cases /app/apps/freight/fixtures/random_current/sth_excel_random_cases.csv `
  --expected /app/apps/freight/fixtures/random_current/sth_excel_random_outputs.csv `
  --components /app/apps/freight/fixtures/random_current/sth_excel_random_components.csv `
  --report /app/reports/random_current/sth_excel_random_comparison_report.csv `
  --fail-on-difference
```

After the command, confirm the four fixed CSV files and the matching baseline are present before recording the result in `docs/12_validation_findings_log.md`.

## Run the retained live_latest battery safely

```powershell
docker compose run --rm --no-deps `
  --env "POSTGRES_DB=$ValidationDb" `
  web python manage.py validate_excel_battery `
  --import-workbook `
  --workbook "/app/sample_data/live_baselines/$LiveBaselineRelative" `
  --replace `
  --cases /app/apps/freight/fixtures/live_latest/sth_excel_generated_cases.csv `
  --expected /app/apps/freight/fixtures/live_latest/sth_excel_generated_outputs.csv `
  --components /app/apps/freight/fixtures/live_latest/sth_excel_generated_components.csv `
  --report /app/reports/sth_excel_live_comparison_report.csv `
  --fail-on-difference
```

Expected retained evidence is 97 OK and 0 FAIL. Record the actual output from
the new run; do not infer success from the historical report.

After completing the validation and retaining the report, remove only the
uniquely named temporary database created above:

```powershell
docker compose exec -T db sh -lc `
  'dropdb --username="$POSTGRES_USER" "$1"' sh $ValidationDb
```

This cleanup does not touch the operational PostgreSQL database or Docker
volume.

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

After a normally completed validation, the command reapplies the active Admin
fuel dataset inside the validation database. When the isolated procedure is
used, the operational Fuel configuration is never replaced.

If an older battery was accidentally run against the operational database and
was interrupted, restore Fuel manually:

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

Record the actual `OK` result; do not infer it solely from source inspection. Then run the standard 0% Excel-vs-Django battery to confirm that default behaviour remains unchanged.

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

## Validate remembered Fuel source URLs

Run the Fuel import suite:

```powershell
docker compose exec web python manage.py test `
  apps.imports.tests.test_fuel_import `
  --noinput `
  -v 2
```

The suite must confirm:

- the configured fallback URL appears when no successful fetch exists;
- an editable HTTP/HTTPS URL is passed to the downloader;
- the selected URL is stored in `ExternalDataFile.source_url`;
- the last successfully validated URL is restored for that client;
- invalid non-HTTP/HTTPS input does not start a download;
- validation, activation, rollback and active-Fuel reapplication remain unchanged.

Confirm no schema change:

```powershell
docker compose exec web python manage.py makemigrations imports --check --dry-run
```

Manual check:

1. Open `Imports → External data files → Fetch fuel from source`.
2. Confirm the current client's remembered URL appears and is editable.
3. Select another client and confirm the URL changes to that client's remembered value or fallback.
4. Fetch and validate a trusted Fuel CSV.
5. Reopen the Fetch page and confirm the validated URL is retained.
6. Confirm activation is still a separate explicit action.

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

The current code contains 16 targeted import tests: 10 Fuel and 6
Product/Stock tests. Record the actual run result; do not claim success from
test count alone.

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

The 2026-08-18 review package reports `manage.py check` successfully and lists
all migrations as applied. Its complete test-suite capture stopped while
creating `test_freight_platform`, and its database-summary command was
malformed. Re-run the commands above in the full project environment before
treating the runtime state as fully verified.

## User-access implementation validation order

When user code is authorised, validate in this order:

```text
1. model/profile validation tests
2. login/logout and inactive-user tests
3. customer client-isolation tests
4. internal selected/all-client tests
5. Admin custom-action permission tests
6. interactive password setup tests; email invitation/reset delivery remains pending
7. existing freight and import regression tests
8. Excel-vs-Django batteries to prove calculation behaviour is unchanged
```

## User access deployment and validation — 2026-07-22

Apply migrations and create the minimum administrator groups:

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
failures in `test_login_security`: the authored generic authentication form is
not connected to the active `CalculatorLoginView`. They are not caused by
group-based access and must be resolved as a separate login-security change.

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

## FTP Fuel validation runbook - 2026-08-27

1. Confirm `fuel.csv` is present directly in the mounted `uploaded_data` folder.
2. Do not edit the source file in place.
3. Run:

```powershell
docker compose exec -T web python manage.py process_uploaded_fuel --client STH --filename fuel.csv
```

4. Require the command to finish with a validated snapshot and the explicit
   message `VALIDATION ONLY. NO FUEL RATES WERE ACTIVATED.`
5. Review warnings for source Rate Cards not used by the client and client Rate
   Cards missing from the source.
6. Any carrier mismatch or unsupported type on a used Rate Card is a FAIL; do
   not activate.
7. If validation passes, review the existing Fuel preview in Django Admin.
8. Activation remains a separate manual action during phase 1.
9. After activation, run the existing Fuel/import regression tests and perform
   a small calculator smoke test using at least one affected Rate Card.
10. Roll back through the existing Fuel rollback operation if operational
    verification fails.

## FTP Fuel detailed preview - 2026-08-27

Before the first activation of a validated FTP Fuel snapshot, run:

```powershell
docker compose exec -T web python manage.py process_uploaded_fuel --client STH --filename fuel.csv
```

The command must display a detailed `MATCHED CLIENT CONFIGURATIONS` table with
Carrier, Service, Rate Card, Current Fuel, New Fuel and CHANGE/UNCHANGED status.
It must also display `CLIENT CONFIGURATIONS MISSING FROM SOURCE` and explicitly
state that their existing Fuel values will be preserved.

Re-running the same unchanged `fuel.csv` must not create another snapshot. The
command reuses the stored validation summary and prints the same preview again.
This allows operational review without changing data or producing duplicate
records.

For the first controlled activation of a new source format, run the complete
Django regression suite after the import tests and before activation:

```powershell
docker compose exec -T web python manage.py test --noinput -v 2
```

Activation remains separate from validation. A successful preview is not an
authorisation to activate if regression tests are failing.

## FTP postcodes validation - 2026-08-27

Run `python manage.py process_uploaded_postcodes --client STH --filename postcodes.csv` after a new FTP drop. Review: rows read, Australian candidate rows, excluded rows, existing matches, rows that would be added, and current Django rows not present in the source. The command must end with `VALIDATION ONLY` and must not change `locations.Suburb`.

Do not implement or run a postcode activation until the `current Django rows not in source` delta has been reviewed. Initial activation should preserve unmatched current rows unless a separate deletion policy is approved and tested with Zones and calculator regression cases.

## FTP postcodes cross-validation - 2026-08-27

After the structural postcodes validation passes, run `process_uploaded_postcodes` again with the Phase 2 implementation. The command remains read-only for `locations.Suburb`, but it cross-validates every prospective addition against the current operational `FreightZone` data for the client.

Decisions are intentionally conservative: `ADD_CANDIDATE` requires an exact suburb/state/postcode zone reference. `REVIEW_ALIAS_LIKELY`, `REVIEW_POSTCODE_CONFLICT`, and `REVIEW_NO_EXACT_ZONE` remain blocked from any future add-only activation until manually resolved. Existing Django suburbs that are absent from the source remain `PRESERVE EXISTING`; this phase never deletes or renames suburbs.

## FTP Zones validation - 2026-08-27

`uploaded_data/zones.csv` is introduced as a validation-only FTP source before any operational activation is implemented.

Run:

```text
python manage.py process_uploaded_zones --client STH --filename zones.csv
```

The command snapshots the immutable source, reuses identical SHA-256 content, validates the CSV index contracts, reports exact duplicate rows, separates Australian/non-Australian rows, flags Australian postcodes that are not exactly four digits without auto-padding them, maps source carrier rows to the current Django carrier service where that mapping is unambiguous, and compares the result with current `FreightZone`, `Suburb`, and `FreightRate` data.

This phase does not add, update, replace, rename, or delete `FreightZone` rows. Current rows missing from the safely mapped source comparison are preserved.

The source has no service column, so ambiguous carrier-to-service mappings are review items and must not be guessed.

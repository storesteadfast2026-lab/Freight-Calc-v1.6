# External File Imports

## 1. Import channels

The project has two different import concepts. They must not be mixed.

### 1.1 Full calculator workbook

The official workbook is imported by management command and supplies the operational base datasets used by the calculator:

```powershell
docker compose exec web python manage.py import_sth_excel /app/sample_data/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx --client STH --replace
```

This channel loads workbook tables such as SKUs, suburbs, carrier configuration, zones, rates and workbook/bootstrap fuel.

### 1.2 Three Django Admin source files

Django Admin currently accepts three external source types:

| File | Type | Current effect |
|---|---|---|
| `product_sth.xlsx` | PRODUCTS | Reference-only staging and comparison against Django Products. |
| `stock_sth.xlsx` | STOCK | Reference-only staging and comparison against Django Products. |
| `fuel.csv` | FUEL | Operational fuel changes only after manual activation. |

Open:

```text
Django Admin → Imports → External data files
```

## 2. Common ExternalDataFile behavior

Every upload/download stores:

- client;
- file type and source method;
- original and stored filename;
- file size and MIME type;
- SHA-256 content hash;
- upload/validation actor and timestamp;
- validation summary and status;
- audit events.

Files are stored under:

```text
/app/uploaded_data/external_imports/<client>/<file_type>/YYYY/MM/
```

Docker persists them through:

```yaml
- ./uploaded_data:/app/uploaded_data
```

Do not commit production uploads to Git.

## 3. Product source — product_sth.xlsx

Use:

```text
Imports → External data files → Upload product source
```

Current workflow:

```text
Upload XLSX
→ calculate SHA-256
→ locate product_sth/products/product worksheet
→ map required headers by accepted aliases
→ validate every non-empty row
→ compare normalized SKUs with operational Product rows
→ replace ProductSourceRow rows for this uploaded file
→ status VALIDATED
→ create audit event
```

Important rules:

- all required Product columns must be identifiable;
- product code is mandatory;
- invalid numeric values reject the entire staging load;
- duplicate product codes inside the same source are treated as validation errors;
- duplicate file content is reported as a warning with the prior file ID;
- empty placeholder rows are skipped;
- the source is `reference_only=True`;
- `operational_tables_updated=False`;
- there is no Activate or Rollback operation.

The summary reports:

- valid/skipped rows;
- duplicate SKUs;
- Django products matched;
- source products not in Django;
- Django products missing from source;
- a 25-row preview.

`Source products not in Django` is a comparison finding, not a signal that products will be created automatically.

## 4. Stock source — stock_sth.xlsx

Use:

```text
Imports → External data files → Upload stock source
```

Current workflow is equivalent to Product source but stores `StockSourceRow` records.

Important differences:

- repeated product codes in Stock are allowed because multiple stock/movement rows can refer to the same SKU;
- duplicates are preserved and reported as a warning;
- invalid rows reject the whole staging load;
- the summary reports Stock SKUs not present in the operational Product table;
- the source is reference-only and has no activation or rollback.

## 5. Fuel source ownership

Fuel has two explicit modes:

1. **Legacy workbook/bootstrap** — used when no active Admin fuel file exists, or when historical Excel validation explicitly requests workbook fuel.
2. **Operational Admin source** — the active `fuel.csv` downloaded/uploaded and activated in Django Admin.

Normal workbook imports use active Admin fuel:

```text
--fuel-source active
```

Historical validation may use:

```powershell
docker compose exec web python manage.py import_sth_excel <baseline.xlsx> --client STH --replace --fuel-source workbook
```

`validate_excel_battery --import-workbook` uses workbook fuel for the historical comparison and normally restores the active Admin fuel dataset afterward.

## 6. Fuel entry paths

### Fetch from official source

```text
Imports → External data files → Fetch fuel from source
```

Initial fallback URL:

```text
https://www.poscat.com.au/fuelsc/fuel.csv
```

Environment settings:

```text
FUEL_SOURCE_URL
FUEL_FETCH_TIMEOUT_SECONDS
FUEL_RATE_MAX
```

The Fetch page exposes the source URL as an editable HTTP/HTTPS field. For each
client, the next Fetch page uses the latest URL belonging to an
`ADMIN_WEB_FETCH` Fuel record that reached a successfully validated lifecycle
status. If none exists, it uses `FUEL_SOURCE_URL`.

Changing the URL does not activate Fuel rates. The downloaded snapshot still
passes the existing validation and requires explicit activation. The selected
URL is stored in `ExternalDataFile.source_url` and in Fuel audit metadata.

Product and Stock continue to use local browser uploads. Django records the
original filename and stored server path, but cannot read or prefill the local
Windows directory selected by the user.

### Upload local CSV

Use `Add external data file`, select `FUEL`, and upload a `.csv` file.

Expected columns:

```text
master_rate,info,rate,updated,expires,warnings
```

Mapping:

```text
fuel.csv.master_rate ↔ ClientCarrierConfig.ratecard
fuel.csv.rate        → ClientCarrierConfig.fuel_levy
```

## 7. Fuel processing and safety

```text
Fetch or upload
→ immutable snapshot and SHA-256
→ validate structure, values, dates, duplicates and coverage
→ display preview
→ activate manually
→ update matching fuel_levy values transactionally
→ record provenance and AuditEvent
```

Validation checks include:

- required columns;
- non-empty data;
- unique `master_rate`;
- numeric range;
- valid update/expiry dates;
- duplicate content;
- file ratecards missing in Django;
- Django ratecards missing in the file.

Expired data is blocked unless a superuser forces activation with a written justification.

Only the active Fuel file can be rolled back. Rollback restores the exact previous value, source and file reference recorded during activation.

Recovery command:

```powershell
docker compose exec web python manage.py reapply_active_fuel --client STH
```

## 8. Import permissions

The delivered source defines explicit permissions for sensitive import actions:

```text
imports.validate_external_data_file
imports.activate_fuel
imports.rollback_fuel
imports.download_external_data_file
```

Standard model permissions continue to govern upload, change and read-only records. The package confirms that migration `imports.0004_external_data_file_permissions` is applied, but the complete targeted test run must still be captured before release approval.

## 9. Verification commands

Migrations:

```powershell
docker compose exec web python manage.py showmigrations imports
```

Expected:

```text
[X] 0003_product_stock_reference_sources
```

Targeted import tests:

```powershell
docker compose exec web python manage.py test apps.imports.tests.test_fuel_import apps.imports.tests.test_product_stock_sources -v 2
```

Operational-table isolation check before and after Product/Stock uploads:

```powershell
docker compose exec web python manage.py shell -c "from apps.products.models import Product; from apps.rates.models import FreightRate,FreightZone; from apps.carriers.models import ClientCarrierConfig; print({'products':Product.objects.count(),'rates':FreightRate.objects.count(),'zones':FreightZone.objects.count(),'configs':ClientCarrierConfig.objects.count()})"
```

The counts must remain unchanged after Product/Stock reference uploads.

## Import authorization update — 2026-07-22

The three Django Admin source flows remain unchanged functionally, but sensitive actions now use explicit permissions:

```text
imports.validate_external_data_file
imports.activate_fuel
imports.rollback_fuel
imports.download_external_data_file
```

Standard `add_externaldatafile`, `change_externaldatafile` and `view_externaldatafile` permissions continue to control upload and record access. Product and Stock validation still writes only staging rows. Fuel still changes operational configuration only after activation.

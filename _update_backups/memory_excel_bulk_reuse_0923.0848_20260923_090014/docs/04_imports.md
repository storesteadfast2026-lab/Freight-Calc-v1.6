# External File Imports

## 1. Import channels

The project has two different import concepts. They must not be mixed.

### 1.1 Full calculator workbook

The official workbook is imported by management command and supplies the operational base datasets used by the calculator:

```powershell
docker compose exec web python manage.py import_sth_excel /app/sample_data/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx --client STH --replace
```

This channel loads workbook tables such as SKUs, suburbs, carrier configuration, zones, rates and workbook/bootstrap fuel.

### 1.1.1 Destructive scope of `--replace`

`import_sth_excel --replace` is not an isolated read operation. For the selected
client it deletes and rebuilds:

```text
Product
FreightRate
FreightZone
CarrierTailgateCharge
ClientCarrierConfig
```

It also deletes every `ExternalDataFile` for that client except `FUEL`.
Because `ProductSourceRow` and `StockSourceRow` use cascading foreign keys,
their database rows are deleted with the corresponding Product/Stock file
records. Django does not automatically remove the physical uploaded files, so
orphaned files may remain under `uploaded_data/`.

Consequences:

- do not run `--replace` against the operational database merely to execute an
  Excel-vs-Django battery;
- use the isolated-database procedure in `docs/11_validation_runbook.md`;
- preserve a PostgreSQL backup before any intentional operational replacement;
- Fuel history is retained, but active Fuel is reapplied only after the normal
  import/validation path completes.

### 1.2 Three Django Admin source files

Django Admin currently accepts three external source types:

| File | Type | Current effect |
|---|---|---|
| `products.xls` (`.csv` and `.xlsx` readers retained) | PRODUCTS | Reference-only staging and comparison against Django Products. |
| `stock_sth.xlsx` | STOCK | Reference-only staging and comparison against Django Products. |
| `fuel.csv` | FUEL | Operational fuel changes only after manual activation. |

Open:

```text
Django Admin → Imports → External data files
```

## 2. Common ExternalDataFile behaviour

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

## 3. Product source — products.xls

Use:

```text
Imports → External data files → Upload product source
```

Current workflow:

```text
Upload Product source
→ calculate SHA-256
→ Product File Adapter selects the registered reader
→ normalise XLS, CSV or XLSX into one canonical record structure
→ validate the 13 required logical fields
→ isolate malformed/invalid/duplicate rows
→ retain valid rows in staging
→ compare Product SKUs as trimmed uppercase text with operational Product rows
→ replace ProductSourceRow rows for this uploaded file
→ status VALIDATED
→ create audit event
```

Important rules:

- the operational source is `products.xls`;
- the physical file reader is isolated from staging, validation, comparison and Product;
- the XLS reader supports the current Translogic legacy BIFF export beyond its declared 16,384-row limit;
- all 22 XLS columns are retained in `raw_data`, while the existing 13 logical Product fields continue through the unchanged staging structure;
- extension and binary content must agree; a binary XLS renamed as CSV is rejected with a specific error;
- all required Product columns must be identifiable;
- product code is mandatory;
- malformed or invalid CSV rows are isolated in `ProductSourceRejectedRow`;
- Product SKU codes preserve meaningful leading zeroes (`0034` and `34` are distinct);
- Product SKU comparison trims surrounding spaces and ignores letter case;
- exact duplicate Product codes after this text normalisation are isolated for review;
- valid rows remain available even when rejected rows exist;
- duplicate file content is reported as a warning with the prior file ID;
- empty placeholder rows are skipped;
- the source is `reference_only=True`;
- `operational_tables_updated=False`;
- there is no Activate or Rollback operation.

### 3.1 Product File Adapter boundary

```text
products.xls / products.csv / product_sth.xlsx
                    ↓
           Product File Adapter
                    ↓
       canonical Product records
                    ↓
ProductSourceRow → validation → reconciliation
```

Adding a future source format requires a reader registered in
`services/product_file_adapters`. The Product staging workflow must not contain
format-specific branches. XML is intentionally not registered until its source
schema is confirmed.

The summary reports:

- valid/skipped rows;
- duplicate SKUs;
- Django products matched;
- source products not in Django;
- Django products missing from source;
- a 25-row preview.

The downloadable validation report includes every valid and rejected row,
source values, comparison status, fields that differ, and the current
operational dimensions/weight/cubic when a Django Product matches. It never
updates the operational Product table.

### 3.2 Product reconciliation workspace

After a Product source file is validated, open:

```text
Imports → External data files → <products.xls> → Product reconciliation workspace
```

The workspace turns the comparison into a review queue without changing the
operational Product table. It provides:

- one-glance groups for zero source dimensions, text-only differences,
  physical differences, other differences, source-only, operational-only,
  duplicate-source and equal rows;
- search and status filters;
- field-level authority choices (`Source`, `Operational`, `Custom` or
  `No change`) for selected rows or the whole active group;
- an individual editor for exceptions, including custom values;
- reusable client rules that can prepare the same draft choices in later
  Product files;
- a preview of the proposed result and its remaining warnings.

The `Edit product` action is displayed directly in the SKU column, which stays
visible while the comparison table scrolls horizontally. Opening it navigates
directly to the individual editor below the table, so editing never depends on
reaching a narrow action column at the far-right edge.

Bulk actions are bounded to 2,000 rows per operation. Larger groups must be
filtered or divided before saving. Source-only rows default to reference-only;
the workspace does not create new operational Products.

All decisions and rule applications are drafts. This release deliberately has
no operational Apply action: it does not update `Product`, Calculator, rates,
zones or freight type. The workspace does, however, propose C/P from the source
`pallet` column using the current Chat.Calc rule: `pallet = 0` proposes `C`
(Case), while `pallet > 0` proposes `P` (Pallet). Empty, negative or
non-numeric values cannot be inferred and require a manual C/P decision.

Reusable rules are review accelerators, not automatic imports. Applying a rule
creates or updates draft decisions that remain visible in the preview before
any future operational implementation is considered.

### 3.3 Controlled repair of malformed Product rows

Malformed rows remain isolated after validation. They are reviewed from the
specific Product source file through `Review rejected rows`; the rejected-row
model is deliberately hidden from the main Imports menu.

For each rejected row Django displays:

- the original parsed values and validation error;
- an editable 13-field reconstruction proposal;
- `Save proposal only`, which does not enter staging;
- `Approve into staging`, which requires a review note.

`Review rejected rows` opens a bulk review screen scoped to that Product source
file. The table shows the complete proposed name, description and comment with
wrapping text, plus the numeric fields beneath each row. A reviewer may search,
filter by review status, select individual rows or select all currently visible
rows. `Edit` expands the 13 proposal fields only for a row that needs a
correction.

The bulk commands apply only to checked rows:

- `Save selected proposals` records drafts without entering staging;
- `Approve selected` requires a common review note and creates reference
  staging rows only for the selected records;
- unselected records remain unchanged;
- the selected batch is atomic: if any selected row fails validation or has a
  conflicting SKU, none of that batch is approved.

The individual rejected-row detail page remains available through `Details`.
The rejected-row model stays hidden from the main Imports menu.

The screen is implemented through a common bulk-review workflow and a
Product-specific adapter. Future import or reconciliation procedures can reuse
the common selection, filtering, edit-panel and atomic-action controls while
supplying their own fields, validation and processing rules.

Approval creates one linked `ProductSourceRow` reference record and records the
reviewer, timestamp, note, original values and approved values. The original
`ProductSourceRejectedRow` remains as immutable evidence with status
`APPROVED`. Operational `Product`, freight type, rates, zones and Calculator
remain unchanged.

Before rolling migration `imports.0010` back, run
`python manage.py rollback_product_repair_review`. It removes only staging rows
created by approved repairs, resets their review state and leaves operational
`Product` data unchanged.

A source file with saved or approved repair reviews cannot be revalidated in
place. Upload a new source snapshot instead; this prevents a revalidation from
silently deleting manual review decisions.

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

Standard model permissions continue to govern upload, change and read-only
records. Migration `imports.0004_external_data_file_permissions` is applied in
the retained deployment evidence. The current source contains 10 Fuel and 6
Product/Stock tests; the remembered-URL installer result must still be captured
before approving that latest change.

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

## Import authorisation update — 2026-07-22

The three Django Admin source flows remain unchanged functionally, but sensitive actions now use explicit permissions:

```text
imports.validate_external_data_file
imports.activate_fuel
imports.rollback_fuel
imports.download_external_data_file
```

Standard `add_externaldatafile`, `change_externaldatafile` and `view_externaldatafile` permissions continue to control upload and record access. Product and Stock validation still writes only staging rows. Fuel still changes operational configuration only after activation.

## 9. FTP uploaded_data Fuel source - phase 1 (2026-08-27)

The Freight Calculator now accepts the operational FTP Fuel schema in addition
to the legacy Admin Fuel schema.

FTP source location inside the Django container:

```text
/app/uploaded_data/fuel.csv
```

The Docker FTP service already mounts the same host `uploaded_data` directory,
so manual FTP drops and future automated transfers use the same ingestion path.

FTP schema:

```text
rate_no,carrier,name,surcharge,type
```

Normalisation into the existing Fuel model:

```text
rate_no   -> master_rate / ClientCarrierConfig.ratecard
carrier   -> independent carrier cross-check against Django configuration
name      -> informational description
surcharge -> percentage divided by 100 before becoming fuel_levy
type      -> explicit source interpretation; phase 1 supports PRICE
```

Example:

```text
1822,KTI,KTI Fuel Surcharge PRICE,42.90,PRICE
```

normalises to a Django fuel levy of `0.429` only after validation.

Run validation manually:

```powershell
docker compose exec -T web python manage.py process_uploaded_fuel --client STH --filename fuel.csv
```

This command is deliberately **validation-only**. It creates an immutable
snapshot, calculates SHA-256, validates the FTP schema and business mapping,
and records the result in `ExternalDataFile`. It does not activate Fuel and it
does not modify `ClientCarrierConfig.fuel_levy`.

The source file in `/app/uploaded_data` is not deleted or modified. Re-running
the command against identical content is idempotent: an existing FTP snapshot
with the same client/file type/SHA-256 is reused rather than creating another
copy.

### Blocking FTP Fuel checks

For any Rate Card configured for the selected client:

- required FTP columns must exist;
- `rate_no`, `carrier`, `surcharge`, and `type` are mandatory;
- `rate_no` must be unique in the file;
- `surcharge` must be numeric and its normalised value must respect
  `FUEL_RATE_MAX`;
- the file `carrier` must match the carrier linked to that Rate Card in Django;
- the source `type` must be explicitly supported; phase 1 supports `PRICE`.

A carrier mismatch on a used Rate Card blocks validation. Example:

```text
rate_no 1115 / file carrier TNT / Django carrier TEAMEX -> FAIL
```

Unsupported types on Rate Cards used by the client also block validation.
Unsupported types on unrelated Rate Cards are warnings because those rows
cannot affect that client's configuration.

## Product reconciliation after rejected-row approval — 2026-09-14

After every rejected Product row has been approved into `ProductSourceRow`, the
validated file exposes a protected **Product reconciliation** operation. The
screen compares the effective staging set against the client's operational
`Product` records used by Calculator.

The comparison reports:

- same and different matched SKU;
- source-only SKU, with C/P proposed from a valid source `pallet` value;
- operational SKU absent from the source;
- duplicate source SKU;
- dimension, weight and cubic differences;
- source dimensions that are all zero while operational dimensions are valid;
- source quantity and comment as review context.

Source millimetres are retained as raw staging values and converted to metres
for comparison. Likely ×10/÷10 scale mismatches are sent to manual review and
are never silently converted. Its C/P proposal uses `pallet = 0 → C` and
`pallet > 0 → P`; missing, negative or invalid values are routed to manual
review. The C/P difference queue is transversal, so the count includes rows
that also have physical differences.

The protected workflow is `Review → Preview → Apply`. The recommended initial
correction creates drafts that use Source `name` and `description`, retain the
Calculator's physical values pending review, and derive C/P from the source
pallet rule. Source-only rows remain reference-only. Operational-only rows can
be proposed for removal, but Apply is blocked when a SKU is referenced by a
kit or saved quotation. Apply is transactional and audited; the latest batch
can be rolled back from the same preview. If any rejected row is still pending,
the comparison and Apply are visibly blocked until review is complete.

The reconciliation page is server-side paginated (100 records per page),
searchable by SKU/name and filterable by review group. Individual edit is
available beside the SKU, while bulk decisions handle product groups.

The legacy workbook bootstrap does not contain Product names/descriptions in
the `SKUs` sheet. Columns B and C are dimensions, so the bootstrap now uses SKU
as a temporary name and a blank description. Authoritative Product text comes
from the validated Product source through reconciliation.

### Product reconciliation decision memory — 2026-09-22

Every successfully applied Product reconciliation decision records an audited
memory scoped to the client, SKU and exact Source values. On a later validated
Product file:

- an identical Source problem prepares the previous approved solution as a
  `DRAFT` automatically;
- the same SKU with changed Source values displays the previous solution for
  comparison, but requires an explicit **Use previous solution** action;
- an administrator may adopt the current Calculator values as approved memory
  only by selecting the rows and entering a reason;
- a repeated file SHA-256 is shown as an additional warning.

Memory never updates operational `Product` rows. Every reused solution still
passes through Preview and explicit Apply. Memories created by an Apply batch
participate in that batch's rollback. Previously applied decisions are
backfilled idempotently when an authorised administrator opens their
reconciliation workspace. Active memories can be inspected and deactivated in
Django Admin; status changes are audited.

### Activation remains unchanged and manual

Once an FTP snapshot is `VALIDATED`, the existing Admin activation and rollback
workflow remains the authority for operational Fuel changes. FTP activation
uses the same transaction, provenance and rollback logic as existing Fuel
sources. No freight calculation rule or carrier pricing formula is changed by
this FTP adapter.

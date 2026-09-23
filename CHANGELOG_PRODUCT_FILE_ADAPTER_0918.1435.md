# Product File Adapter — 0918.1435

## Scope

This update changes only the Product source ingestion boundary.

## Included

- Adds a registered Product File Adapter layer.
- Makes `products.xls` the current Product source presented by Admin and the FTP inbox.
- Adds a legacy XLS reader compatible with the current Translogic export.
- Prevents the declared 16,384-row BIFF limit from truncating the current source.
- Retains existing CSV and XLSX readers behind the same adapter.
- Verifies that filename extension and actual file content agree.
- Preserves all additional XLS columns in `ProductSourceRow.raw_data`.
- Adds `xlrd==2.0.1` for read-only legacy XLS support.

## Unchanged

- No database migration.
- No change to `ProductSourceRow`, `Product` or Calculator schemas.
- No automatic Apply to operational Product.
- No change to Product reconciliation decisions.
- No change to Fuel, Postcodes or Stock readers and processing.

## Verification

- The supplied `products.xls` was read as 38,631 data rows and 22 columns.
- All 38,631 rows entered isolated Product staging in the integration test.
- No Product, rate, carrier configuration or calculation table was updated.
- 127 Imports tests passed.

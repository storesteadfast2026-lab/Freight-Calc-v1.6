# Validation Findings Log

## 2026-07-17 - Fuel source moved to manual Django Admin activation

### Decision

Operational fuel rates are no longer owned by the cached `FuelSurcharge!K` value after an Admin fuel dataset has been activated. Django downloads or accepts `fuel.csv`, validates it, previews changes and updates `ClientCarrierConfig.fuel_levy` transactionally.

### Compatibility

- Workbook fuel remains available as a legacy bootstrap.
- Normal workbook imports reapply the active Admin fuel dataset.
- Excel-vs-Django historical validation explicitly uses workbook fuel and restores active operational fuel after a completed run.
- A recovery command is available: `python manage.py reapply_active_fuel --client STH`.

### Verification

Automated tests added for valid activation, invalid CSV preservation, duplicate active files, expired-file controls, rollback and reapplication after config rebuild.

Current targeted result:

```text
7 tests passed
- 5 fuel import tests
- 2 existing freight tests
```

This log records calculation mismatches, root causes, corrections, and validation results. It is the operational memory for Excel-to-Django parity.

## 2026-07-14 - TEAMTAS GENERAL fix and validation baseline refresh

### Summary

A random Excel-vs-Django validation battery detected a real calculation issue for `TEAMTAS GENERAL`.

Failing case:

```text
Case: RANDOM_004
Destination: WEEGENA TAS 7304
Product: BRH4443 x 2
Excel expected: 828.03
Django actual before fix: 663983.07
```

### Root cause

Django treated `TEAMTAS GENERAL` as a normal kg-based carrier. That effectively calculated:

```text
rate * kilograms
```

Excel does not calculate `TEAMTAS GENERAL` that way. The workbook uses carrier-specific logic in `BrokerTotals` row 20 based on whole tonne/cubic chargeable units and an additional TEAMTAS fee.

### Resolution

`calculator.py` was updated with TEAMTAS-specific logic:

- chargeable units are based on the greater of rating cubic units and actual tonnes
- chargeable units are rounded up to whole units
- base freight uses `Basic * rating_units + subsequent + Rate * whole_chargeable_units`
- an additional TEAMTAS fee is added:

```text
(pallet_count * 2) + (visible_cubic * 0.6)
```

### Important baseline finding

After the TEAMTAS fix, `random_current` passed, but `live_latest` initially showed many failures.

This was not a Django calculation regression. The cause was that the existing `live_latest` expected CSV files were not aligned with the current base workbook/baseline.

Rule confirmed:

```text
Each validation battery must use the Excel baseline that generated its expected CSV files.
```

Do not mix:

- expected CSV from one baseline
- PostgreSQL data imported from another baseline

Doing so can produce false failures even when Django calculation logic is correct.

### Historical validation results recorded on 2026-07-14

Real 20-case battery:

```text
Cases run: 20
Expected output rows loaded: 77
Report rows: 97
OK rows: 97
FAIL rows: 0
```

Random 15-case battery:

```text
Cases run: 15
Expected output rows loaded: 21
Report rows: 36
OK rows: 36
FAIL rows: 0
```

### Status interpretation

```text
TEAMTAS GENERAL: fixed in documented code and covered by historical regression
live_latest: passing in the report included with the 2026-07-22 package
random_current: historical passing result only; current package evidence incomplete
Excel-Django workflow: valid when CSVs and their matching workbook baseline remain paired
```

## Earlier confirmed findings

### Visible cubic vs rating cubic

`Calculator!J24` is the visible/customer cubic. `CalcLines!P29` can include pallet cubic and is used internally for rating.

Django consolidation includes pallet cubic, so visual comparison may need:

```text
visible_cubic = rating_cubic - pallet_count * 0.02
```

### Zone resolution order

Excel behavior requires exact `suburb + state` match before postcode-only fallback. Many Australian suburbs share postcodes.

TEAMEX must not freely fall back to postcode-only aliases when Excel does not rate the carrier that way.

### KTI precision

KTI required higher decimal precision in imported rates. `FreightRate` decimal precision was increased to preserve six decimal places.

## 2026-07-17 — PostgreSQL row-lock failure during fuel activation

- **Status:** Corrected in hotfix `0717.1552`.
- **Observed in:** `apps.imports.tests.test_fuel_import` using PostgreSQL.
- **Error:** `FOR UPDATE cannot be applied to the nullable side of an outer join`.
- **Root cause:** `select_for_update()` was combined with
  `select_related('fuel_data_file')`; the nullable foreign key generated a
  `LEFT OUTER JOIN` that PostgreSQL cannot lock.
- **Change:** removed the nullable join and restricted the lock to
  `ClientCarrierConfig` with `select_for_update(of=('self',))`.
- **Business logic impact:** none. Fuel matching, validation, activation,
  rollback and audit behavior remain unchanged.
- **Regression command:**
  `docker compose exec web python manage.py test apps.imports.tests.test_fuel_import -v 2`.

## 2026-07-17 — Fuel validation summary readability

- **Status:** Implemented in UI patch `0717.2220`.
- **Issue:** `ExternalDataFile.validation_summary` was displayed as a large raw JSON block in Django Admin.
- **Change:** the existing JSON is now rendered as summary cards, a rate comparison table, warning/error panels, ratecard coverage and collapsed raw JSON.
- **Data impact:** none. The JSON stored in PostgreSQL is unchanged.
- **Calculation impact:** none.
- **Migration required:** no.
- **Deployment:** replace `admin.py`, add the summary template, and restart the `web` container.

## 2026-07-17 — Compact fuel validation summary

- **Status:** Implemented in UI patch `0717.2237`.
- **Issue:** The first structured summary remained too detailed for an experienced technical administrator.
- **Change:** the primary view now shows a one-line status, operational counts and only configurations whose fuel rate will change.
- **Collapsed by default:** unchanged configurations, matched/unused ratecards, complete metadata and raw JSON.
- **Data impact:** none.
- **Calculation impact:** none.
- **Migration required:** no.

## 2026-07-22 — Product/Stock reference imports confirmed in current code

- **Status:** Implemented, documentation updated.
- **Files:** `product_sth.xlsx` and `stock_sth.xlsx`.
- **Behavior:** upload, SHA-256, validation, audit and isolated source-row storage.
- **Operational impact:** none; `Product`, `FreightRate`, `FreightZone`, `ClientCarrierConfig` and calculation code are not updated.
- **Duplicate behavior:** Product duplicate SKUs inside one file fail validation; Stock duplicate SKUs are preserved with a warning; duplicate file content is reported.
- **Activation:** Product/Stock files have no Activate or Rollback operation.
- **Evidence:** migration `imports.0003_product_stock_reference_sources`, service code and 6 Product/Stock tests.

## 2026-07-22 — Review package runtime diagnostics incomplete

- **Django check:** passed.
- **Migrations:** all listed migrations applied.
- **Complete suite:** not confirmed; capture stopped at test-database creation.
- **Database summary:** not confirmed; generated `manage.py shell -c` command was malformed.
- **Required action:** rerun targeted tests and row-count commands from `docs/11_validation_runbook.md`.

## 2026-07-22 — User/access proposal review

- **Historical status:** This review identified that calculator endpoints lacked user/client scope and custom Admin actions relied too broadly on `is_staff`.
- **Decision:** Keep only Customer User and Internal User calculator roles; keep Django Admin separate.
- **Correction to Codex draft:** quotation visibility/draft/finalization/PDF/email rules remain pending because no persisted Quotation model exists.
- **Implemented outcome:** one `Django Administrator` group, Technical Superusers, calculator profiles, backend client authorization and explicit import-action permissions.

## 2026-07-22 — random_current evidence set incomplete in review package

- **Expected contract:** fixed `random_current` directories and fixed filenames for cases, outputs, components and report.
- **Observed:** `app/apps/freight/fixtures/random_current/sth_excel_random_cases.csv` contains 5 cases.
- **Missing:** random outputs, random components, matching baseline under `sample_data/live_baselines/random_current/` and comparison report under `reports/random_current/`.
- **Legacy artifacts:** `random_5` and `random_30` directories still exist and conflict with the current no-count-folder rule.
- **Conclusion:** do not report `random_current` as currently passing from this package. Preserve the old 15-case/36-OK result as historical evidence and regenerate a complete fixed-folder set before the next calculation change.
- **Runbook:** follow `docs/11_validation_runbook.md`.

## 2026-07-22 — Cubic Margin manual code change reviewed

- **Status:** Implemented in current code; runtime suite result not captured in the review ZIP.
- **Commit evidence:** Git metadata identifies commit `0444bb2` with the Cubic Margin implementation.
- **Range:** blank/0 or whole numbers 1–20; negative, decimal and >20 values are rejected in frontend and backend.
- **Formula:** apply the percentage to visible/product cubic, round upward to 3 decimals, then add pallet cubic back unchanged.
- **Order:** consolidation → Cubic Margin → consolidated validation → carrier rating.
- **Excel status:** `WEB_ONLY`; no equivalent input has been confirmed in the workbook. Default 0% preserves Excel parity.
- **Tests present:** 7 tests in `test_cubic_margin.py`; rerun them in Docker and then rerun the 0% Excel battery.
- **Calculation risk:** non-zero margin intentionally changes chargeable cubic and potentially carrier estimates; it must not be included silently in Excel-parity fixtures.

## 2026-07-22 — User access Version 1

- **Finding:** Calculator and APIs were public and accepted browser-supplied client identifiers.
- **Resolution:** Added session authentication, calculator profiles and centralized backend client authorization.
- **Finding:** Django `is_staff` was sufficient for several custom import/audit views.
- **Resolution:** Added minimum administrator middleware and explicit permissions for validate, activate, rollback and download operations.
- **Finding:** Codex proposal included quotation actions that have no current persistent model.
- **Resolution:** Quotation permissions remain pending and were not implemented.
- **Verification status:** New tests were authored. Full execution must be completed in Docker because the review environment did not contain Django or Docker.

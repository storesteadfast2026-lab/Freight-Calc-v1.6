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

## 2026-07-24 — Calculator access error escaped the login interface

- **Observed:** an authenticated Django user without `CalculatorUserProfile` received a blank page containing `This user does not have a calculator access profile.`
- **Root cause:** `calculator_access_required` returned `HttpResponseForbidden` directly for non-API requests.
- **Security concern:** the browser exposed an internal entitlement reason and left an authenticated-but-unauthorized session active.
- **Resolution:** introduced entitlement-aware `CalculatorLoginView`; unauthorized sessions are cleared and all public feedback is rendered inside the login card with a generic message.
- **CSRF behavior:** CSRF remains enabled. Front-end CSRF failures now use the login-card visual response; API failures remain JSON and Django Admin retains its own behavior.
- **Calculation impact:** none.
- **Migration required:** no.
- **Verification:** run `apps.authentication_gateway.tests.test_login_flow` and `apps.freight.tests.test_user_access` in Docker.

## 2026-07-24 — Login animation differed from the supplied visual reference

- **Observed:** the current login content appeared with opacity fade while already centred.
- **Expected:** the complete card moves from above to the centre and its logo/fields fade in sequentially.
- **Root cause:** the implementation did not preserve the supplied `wrapper fadeInDown` hook and delayed `fadeIn` classes.
- **Resolution:** introduced a dedicated `login.css` and restored the approved HTML animation hooks while preserving Django authentication, CSRF and login-card messages.
- **Security impact:** none.
- **Calculation impact:** none.
- **Migration required:** no.
- **Regression:** `test_login_template_preserves_approved_animation_hooks` verifies the stylesheet and class hooks.


<!-- USER_ADMIN_INTEGRATION_0727.0802 -->
## 2026-07-27 — UserAdmin integration

Confirmed cause: creating a user in Django Admin created `auth.User` but not `CalculatorUserProfile`. The workflow now exposes the optional calculator profile in the same User screen. No calculation or schema change was made.


## 2026-07-27 — FreightCalculator removed from Django Admin

- **Scope:** Administrative visibility only.
- **Reason:** The current calculation flow does not use the `FreightCalculator` Admin record to select formulas, rates, zones or an active engine.
- **Change:** `Client` remains registered; `FreightCalculator` is no longer registered in Django Admin.
- **Database impact:** None. The model, table, records and migrations remain unchanged.
- **Calculation impact:** None expected; no freight calculation code was modified.
- **Verification:** `apps.clients.tests.test_admin_visibility` confirms the expected Admin registration state.
- **ADR:** `docs/adr/0007_hide_unused_freight_calculator_admin.md`.


## 2026-07-28 — Documentation canonicalization and completion

- **Finding:** duplicate user rules, duplicate decision logs, placeholder Product/Rate/Quotation files and numbering collisions allowed contradictory interpretations.
- **Resolution:** established canonical `business_rules/`, `decisions/functional_decisions.md` and uniquely numbered ADR/doc paths; historical duplicates now point to canonical files.
- **Finding:** the authentication traceability matrix still described Version 1 as proposed/not implemented.
- **Resolution:** updated it to `IMPLEMENTED_IN_SOURCE / RUNTIME_RECHECK`, consistent with the delivered source and incomplete packaged test capture.
- **Finding:** documentation used the historical `C:\Docker-Projects\Freight-Calc-Nuevo` path.
- **Resolution:** all operational commands now use `C:\Docker-Projects\Freight-Calc-Nuevo`.
- **Finding:** Product, Rate and Quotation business-rule files were placeholders.
- **Resolution:** Product and Rate files now contain only confirmed behavior plus explicit Excel-dependent pending items; Quotation remains an explicit pending specification because no model exists.
- **Calculation impact:** none. No Python, migration, template, CSS, CSV, report or workbook content was changed.

## 2026-07-30 — Group-only User permissions

- **Status:** Implemented and validated in the review runtime; Docker installer verification remains required in the complete repository.
- **Requirement:** remove individual `User permissions` from User administration and assign access through one primary group.
- **Groups:** `Administrators`, `Customers`, `Steadfast Users`.
- **Mapping:** Administrators → Internal/All clients/staff; Customers → Customer/Single client/non-staff; Steadfast Users → Internal/All clients/non-staff.
- **Super User:** native Django account `super`; no primary group required.
- **Transition:** the legacy `Django Administrator` group is renamed when safe. Existing direct permissions are reported, not silently removed.
- **Schema impact:** none; built-in User, Group, Permission and the existing CalculatorUserProfile remain unchanged.
- **Calculation impact:** none; no freight, import, rate, Excel or Docker logic changed.
- **Verification completed:** Django system check; 28 group/access/admin/login-flow tests; 31 freight/import/client regression tests. All passed.
- **Known unrelated baseline:** four `test_login_security` assertions expect a generic message different from the current baseline login form. This patch does not alter that form.
- **Deployment verification:** run `setup_access_roles` only after the installer completes Django checks and the two targeted test sets.
- **ADR:** `docs/adr/0010_group_based_user_access.md`.

## 2026-07-30 — ProductKitComponent hidden from Django Admin

- **Finding:** `ProductKitComponent` was displayed in the operational Admin even though no current calculation, import, view or service references it.
- **Resolution:** removed only its Django Admin registration. `Product` remains registered.
- **Preserved:** model, table, migration, permissions and any existing records.
- **Schema impact:** none.
- **Calculation and Excel impact:** none.
- **Verification completed:** Django check and Product migration check passed; 21 Product/Client Admin and freight regression tests passed.
- **ADR:** `docs/adr/0011_hide_unused_product_kit_component_admin.md`.

## 2026-07-31 — Calculator presentation-only refresh

- **Requirement:** adopt the approved navy/gold two-column calculator design without the staged `Destination / Shipment / Compare rates` strip.
- **Changed:** calculator template structure, calculator-scoped CSS and a display-only visible-row counter.
- **Preserved:** all existing field IDs, JavaScript calculation/autocomplete functions, API endpoint, payload keys and backend services.
- **Excluded:** Save shipment, quotation history, result-detail arrows and any other unimplemented action.
- **Schema impact:** none.
- **Calculation and Excel impact:** none.
- **Verification completed:** Django check and migration check passed; 63 authentication, calculator, import, client and Product Admin tests passed, including two new DOM-contract tests.
- **Browser QA:** the installer requires final visual confirmation in Docker at desktop, tablet and mobile widths.
- **ADR:** `docs/adr/0012_calculator_visual_refresh.md`.

## 2026-08-03 — Editable, remembered Fuel source URL

- **Requirement:** allow an administrator to edit the Fuel fetch URL and reuse the last valid location on future fetches.
- **Persistence:** reuse `ExternalDataFile.source_url`; choose the latest successfully validated `ADMIN_WEB_FETCH` URL separately for each client.
- **Fallback:** retain `FUEL_SOURCE_URL`, currently `https://www.poscat.com.au/fuelsc/fuel.csv`, when no successful client history exists.
- **Safety:** accept HTTP/HTTPS form input only; invalid input does not start a download; activation remains explicit.
- **Product/Stock boundary:** unchanged local uploads; original filenames remain in history, while browser-local directories cannot be read or prefilled.
- **Schema impact:** none.
- **Calculation and Excel impact:** none.
- **Verification authored:** default URL, custom URL hand-off and storage, per-client remembered URL, and invalid URL rejection; Docker execution required by the installer.
- **ADR:** `docs/adr/0013_remembered_fuel_source_url.md`.

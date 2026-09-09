# Documentation Status and Canonical Sources

**Status:** CURRENT after documentation audit
**Reviewed:** 2026-08-19 08:10 Australia/Adelaide
**Scope:** branch `main` at commit `6197775e57e2917c83b715e3991c342899977e95`; code, documentation and evidence included in review package `0818.1318`.

## Canonical sources

| Subject | Canonical source |
|---|---|
| Business rules | `business_rules/*.md` |
| Functional decisions | `decisions/functional_decisions.md` |
| Technical decisions | `docs/adr/*.md` |
| Calculation explanation | `docs/02_calculation_flow.md` |
| Validation procedure | `docs/10_excel_django_validation_strategy.md`, `docs/11_validation_runbook.md` |
| Findings/history | `docs/12_validation_findings_log.md` |
| Excel-to-Django coverage | `docs/14_excel_django_traceability_matrix.md` |
| AI continuation prompt | `docs/20_ai_project_continuation_prompt.md` |
| Project language standard | `docs/22_language_policy.md` |

Compatibility files under `docs/business rules/` and `docs/decisions/` are non-normative pointers.

All documentation uses Australian English except
`docs/20_ai_project_continuation_prompt.md`, which is intentionally maintained in
neutral Spanish for use as the AI continuation prompt.

## Evidence confirmed

- `REFERENCE_FILES.txt` records the controlled workbook at
  `reference_files/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx` with SHA-256
  `8b7ad87349e6c05656fa44192d8b994fcd2e82f390482b60b27e237a606cafc9`.
- `DJANGO_CHECK.txt` dated 2026-08-18 records `manage.py check` with no issues,
  and `MIGRATIONS_STATUS.txt` records all listed migrations as applied.
- `live_latest` includes 20 cases, 77 expected carrier rows, 20 component rows and a 97-row report with 97 OK / 0 FAIL.
- The 2026-07-31 UI installer recorded 63 related tests passing and the user
  confirmed the refreshed calculator visually.
- Group/client authorisation, integrated UserAdmin, import permissions,
  ProductKitComponent hiding and FreightCalculator hiding are present in source
  and covered by their retained targeted results.

## Evidence incomplete or pending

- `random_current` contains only the five-case input file; outputs, components,
  matching baseline and report are absent.
- The full 72-test source suite is not passing: four of five
  `test_login_security` tests remain open because the authored authentication
  form is not wired into the active login view.
- The remembered Fuel URL change is implemented in source, but a successful
  focused Docker test result is not captured in this package.
- The full repository contains several Excel baselines. The retained
  `live_latest` evidence should record the exact baseline SHA-256 alongside the
  three fixture hashes; filename and timestamp alone are insufficient.
- `TEST_RESULTS.txt` does not contain a completed suite; capture stopped while
  creating `test_freight_platform`.
- `DATABASE_SUMMARY.txt` contains no row counts because the generated shell
  command was malformed.
- This review ZIP omits `docker/django/Dockerfile`, operational `sample_data/`
  contents and the paired Excel baselines. These omissions describe the package,
  not necessarily the full repository.

## Open functional items — do not infer formulas

| Item | Status | Required closure evidence |
|---|---|---|
| Exact overlength calculation | PENDING_EXCEL | directed workbook case, matching baseline and comparison report |
| TEAMTAS GENERAL regression coverage | IMPLEMENTED / HISTORICALLY VALIDATED / NEEDS RETAINED TARGETED CASE | regenerate WEEGENA / BRH4443 x 2 with outputs, components, baseline and report |
| Mixed P/C behaviour | PARTIAL | directed Excel-vs-Django cases |
| Quantities greater than one and visible/rating cubic boundaries | PARTIAL | directed component cases |
| Hand unload | PARTIAL | isolated enabled/disabled cases |
| Warehouse handling | PARTIAL | isolated enabled/disabled cases |
| Quotation model and permissions | PENDING_SPECIFICATION | approved model/lifecycle/security specification |
| Email invitation/password-reset delivery | PENDING_INFRASTRUCTURE | SMTP configuration and end-to-end tests |

## Documentation corrections completed on 2026-07-28

- established canonical rule and decision locations;
- converted duplicate historical files to pointers;
- completed Product, Rate and Quotation scope documents without inventing formulas;
- corrected obsolete authentication traceability rows;
- established the intended unique ADR/document numbering, although two legacy
  duplicate filenames remained and were converted to noncanonical pointers on
  2026-08-04;
- replaced the old project path with `C:\Docker-Projects\Freight-Calc-Nuevo`;
- distinguished implemented source from runtime-verified evidence;
- documented review-package limitations explicitly.
- added a canonical, reusable AI continuation prompt aligned with the normalised documentation and current package evidence.

## 2026-07-30 group-based access update

- Implemented in source: protected primary groups `Administrators`, `Customers` and `Steadfast Users`.
- Implemented in source: User form without individual permissions, manual staff or manual superuser assignment.
- Implemented in source: automatic group-to-profile/client-scope/staff mapping.
- Super User terminology: native account `super`; calculator profile optional.
- Database schema: unchanged.
- Runtime status: Django check, 28 affected access tests and 31 freight/import/client regressions passed in the review runtime; the installer repeats them in Docker.
- Known status: four `test_login_security` message assertions remain open and
  are part of the login-security implementation, not an unrelated baseline.
- Calculation status: unchanged; no freight or Excel files were modified.

## 2026-07-30 ProductKitComponent Admin visibility

- The unused `ProductKitComponent` screen is hidden from Django Admin.
- `Product` remains registered and operational.
- The compatibility model, migration, table, permissions and data remain intact.
- No calculation, import, Excel or database-schema behaviour changed.
- Validation status: Django check, Product migration check and 21 targeted/regression tests passed in the review runtime.

## 2026-07-31 calculator visual refresh

- Responsive Route, Shipment, Shipment summary and freight-options layout implemented in source.
- Staged `Destination / Shipment / Compare rates` navigation intentionally excluded.
- Existing calculator DOM, JavaScript request and backend calculation contracts retained.
- Two dedicated visual-contract tests added.
- Validation status: Django check, migration check and 63 related regression tests passed in the review runtime.
- Docker tests and browser confirmation were completed by the user after
  installation.

## 2026-08-03 remembered Fuel source URL

- Fuel fetch URL is editable and validated as HTTP/HTTPS.
- The latest successfully validated fetched URL is remembered separately for each client using existing `ExternalDataFile` history.
- `FUEL_SOURCE_URL` remains the fallback for clients without successful fetched-Fuel history.
- Product and Stock local-upload behaviour is unchanged.
- No model, migration, calculation, Excel, activation or rollback behaviour changed.
- Focused Fuel import tests and affected regressions are configured in the
  installer; their actual Docker result must be captured after execution.

## 2026-08-04 documentation safety correction

- Excel batteries now require a uniquely named isolated PostgreSQL database.
- Release commands include `--fail-on-difference`.
- The destructive scope of `import_sth_excel --replace` is documented,
  including deletion of non-Fuel Product/Stock import records and staging rows.
- Obsolete public-calculator and broad-`is_staff` troubleshooting guidance was
  replaced with the implemented session/group/permission model.
- Traceability and Admin dictionary rows now describe hidden models and
  server-authorised client selection correctly.
- Import-test inventory is 10 Fuel plus 6 Product/Stock tests.
- No application code, Excel file, fixture, report or database was changed by
  this documentation correction.

# Documentation Status and Canonical Sources

**Status:** CURRENT after documentation audit  
**Reviewed:** 2026-08-04 13:45 Australia/Adelaide  
**Scope:** current documented source through the remembered Fuel URL change; historical review-package evidence is identified separately.

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

Compatibility files under `docs/business rules/` and `docs/decisions/` are non-normative pointers.

## Evidence confirmed

- A historical review confirmed that the separately uploaded workbook and
  `reference_files/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx` matched by
  SHA-256.
- Prior installers recorded `manage.py check` with no issues and migrations
  applied.
- `live_latest` includes 20 cases, 77 expected carrier rows, 20 component rows and a 97-row report with 97 OK / 0 FAIL.
- The 2026-07-31 UI installer recorded 63 related tests passing and the user
  confirmed the refreshed calculator visually.
- Group/client authorization, integrated UserAdmin, import permissions,
  ProductKitComponent hiding and FreightCalculator hiding are present in source
  and covered by their retained targeted results.

## Evidence incomplete or pending

- `random_current` contains only the cases file; outputs, components, matching baseline and report are absent.
- The full 72-test source suite is not passing: four of five
  `test_login_security` tests remain open because the authored authentication
  form is not wired into the active login view.
- The remembered Fuel URL change is implemented in source, but its Docker
  installer result has not been captured in this documentation snapshot.
- The full repository contains several Excel baselines. The retained
  `live_latest` evidence should record the exact baseline SHA-256 alongside the
  three fixture hashes; filename and timestamp alone are insufficient.
- Historical review ZIP omissions, including a missing Dockerfile, are not the
  current repository state and are retained only as historical context.

## Open functional items — do not infer formulas

| Item | Status | Required closure evidence |
|---|---|---|
| Exact overlength calculation | PENDING_EXCEL | directed workbook case, matching baseline and comparison report |
| TEAMTAS GENERAL regression coverage | IMPLEMENTED / NEEDS RETAINED TARGETED CASE | targeted case retained with baseline |
| Mixed P/C behavior | PARTIAL | directed Excel-vs-Django cases |
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
- added a canonical, reusable AI continuation prompt aligned with the normalized documentation and current package evidence.

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
- No calculation, import, Excel or database-schema behavior changed.
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
- Product and Stock local-upload behavior is unchanged.
- No model, migration, calculation, Excel, activation or rollback behavior changed.
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
  server-authorized client selection correctly.
- Import-test inventory is 10 Fuel plus 6 Product/Stock tests.
- No application code, Excel file, fixture, report or database was changed by
  this documentation correction.

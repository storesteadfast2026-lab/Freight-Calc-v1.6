# Documentation Status and Canonical Sources

**Status:** CURRENT  
**Reviewed:** 2026-07-28 12:53 Australia/Adelaide  
**Scope:** `Create_Files_review_0728.0824.zip` and the separately supplied base workbook.

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

## Evidence confirmed in the supplied package

- The separately uploaded workbook and `reference_files/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx` have matching SHA-256 according to the completed review.
- `manage.py check` completed with no issues.
- The captured migration list shows all included migrations applied.
- `live_latest` includes 20 cases, 77 expected carrier rows, 20 component rows and a 97-row report with 97 OK / 0 FAIL.
- The source contains implemented authentication, calculator-client authorization, integrated UserAdmin, import permissions and FreightCalculator Admin hiding.

## Evidence not complete in the supplied package

- The complete Django test run stopped while creating the test database.
- `DATABASE_SUMMARY.txt` contains a malformed shell invocation and no row counts.
- `random_current` contains only the cases file; outputs, components, matching baseline and report are absent.
- The `live_latest` matching Excel baseline is not included under the expected `sample_data/live_baselines/` path.
- The review ZIP does not contain `docker/django/Dockerfile`; it is not a standalone deployment package.

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
- resolved duplicate ADR, document and decision numbering;
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
- Known baseline status: four unrelated `test_login_security` message assertions remain open and are documented in the validation log.
- Calculation status: unchanged; no freight or Excel files were modified.

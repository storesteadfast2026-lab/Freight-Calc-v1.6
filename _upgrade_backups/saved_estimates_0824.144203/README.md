# STH Freight Platform

Django/PostgreSQL application for migrating the logic in `V2026.R2_Unlocked_STH_Freight_Calculator.xlsx` to a multi-client web platform.

## Current status and evidence

**Documentation review:** 2026-08-19 08:10 Australia/Adelaide  
**Code reviewed:** `main` branch, commit `6197775e57e2917c83b715e3991c342899977e95`

The project uses the Excel workbook as the functional source of truth and compares results calculated by Django with expected outputs generated independently by Excel.

Retained evidence for `live_latest`:

```text
live_latest: 20 cases, 77 results + 20 components = 97 OK / 0 FAIL
```

Historical documentation records an earlier `random_current` run with 15 cases and 36 OK rows. The set included in the 18 August 2026 package remains incomplete: it contains five cases but does not contain the paired outputs, components, baseline or report. The historical result must not be presented as a currently reproducible run.

Latest state confirmed by the included code and evidence:

- The dedicated `TEAMTAS GENERAL` branch is already implemented; it is not awaiting an initial fix.
- The correction has historical evidence, but the targeted `WEEGENA / BRH4443 x 2` case is no longer retained in `random_current` with its baseline and report. Regenerate it before changing that branch again.
- The retained canonical `live_latest` report contains 97 OK / 0 FAIL, but this ZIP does not include the paired baseline or SHA-256 manifest. The complete battery therefore cannot be reproduced from the package alone.
- `DJANGO_CHECK.txt` confirms that `manage.py check` completed without errors, and `MIGRATIONS_STATUS.txt` records the applied migrations.
- `TEST_RESULTS.txt` does not confirm the complete suite: capture stopped while creating `test_freight_platform`. `DATABASE_SUMMARY.txt` also lacks record counts because the packaged command was malformed.

## Run with Docker on Windows

```bash
copy .env.example .env
docker compose up --build
```

Then open:

```text
http://localhost:8000/
http://localhost:8000/admin/
```

## Create a superuser

```bash
docker compose exec web python manage.py createsuperuser
```

## Import the STH workbook

The official STH workbook must be located at:

```text
sample_data/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx
```

Manual import:

```bash
docker compose exec web python manage.py import_sth_excel /app/sample_data/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx --client STH --replace
```

## Excel-vs-Django validation

Always validate a battery with the Excel baseline that generated its expected CSV files.

An import using `--replace` rebuilds client data and deletes non-Fuel Product/Stock reference records from the selected database. Batteries must therefore run in an isolated PostgreSQL database, never in the daily operational database. Follow the safe procedure in `docs/11_validation_runbook.md`.

Example for `live_latest`:

```bash
docker compose run --rm --no-deps --env "POSTGRES_DB=<ISOLATED_VALIDATION_DB>" web python manage.py validate_excel_battery --import-workbook --workbook /app/sample_data/live_baselines/<MATCHING_BASELINE>.xlsx --replace --cases /app/apps/freight/fixtures/live_latest/sth_excel_generated_cases.csv --expected /app/apps/freight/fixtures/live_latest/sth_excel_generated_outputs.csv --components /app/apps/freight/fixtures/live_latest/sth_excel_generated_components.csv --report /app/reports/sth_excel_live_comparison_report.csv --fail-on-difference
```

See also:

```text
docs/10_excel_django_validation_strategy.md
docs/11_validation_runbook.md
docs/12_validation_findings_log.md
```

## Documentation

See the `docs/` directory.

Key documents:

- `docs/02_calculation_flow.md`: calculation flow and carrier-specific rules.
- `docs/07_testing_strategy.md`: testing strategy.
- `docs/10_excel_django_validation_strategy.md`: Excel-vs-Django strategy.
- `docs/11_validation_runbook.md`: operational commands.
- `docs/12_validation_findings_log.md`: defect and finding history.
- `docs/13_ai_spec_driven_workflow.md`: AI-assisted, specification-driven workflow.
- `docs/14_excel_django_traceability_matrix.md`: Excel-to-Django traceability matrix.
- `docs/15_admin_configuration_dictionary.md`: Django Admin configuration dictionary.
- `docs/16_user_access_review_and_plan.md`: user/access implementation record and outstanding items.
- `docs/17_user_admin_runbook.md`: user administration through Django Admin.
- `docs/18_login_security_and_ui.md`: login security and design.
- `docs/19_documentation_status.md`: canonical map, included evidence and current outstanding items.
- `docs/20_ai_project_continuation_prompt.md`: updated master prompt for continuing the project with AI. This is the only project document intentionally maintained in Spanish.
- `docs/22_language_policy.md`: Australian English standard and the Spanish prompt exception.
- `business_rules/`: approved or proposed functional rules.
- `decisions/`: functional decision record.
- `docs/adr/`: permanent technical decisions.

## Prompt for continuing the project with AI

To begin a new conversation without relying on chat history, use the canonical prompt:

```text
docs/20_ai_project_continuation_prompt.md
```

The prompt is intentionally written in Spanish. It requires the next session to review repository evidence first, distinguishes implementation and validation states, preserves fixed battery paths and prevents outstanding items from being treated as confirmed rules.

All other project documentation, application text, comments and docstrings use Australian English. See `docs/22_language_policy.md`.

## Complete project and review snapshots

Review ZIP files do not replace the complete repository. In the package generated on 18 August 2026, the controlled workbook copy is located at:

```text
reference_files/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx
```

Operational commands continue to use the full-project path:

```text
sample_data/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx
```

The reviewed package does not include `docker/django/Dockerfile`, the populated operational `sample_data/` directory, the required baselines or the `live_latest` manifest. It supports code review and inspection of retained evidence, not a complete build or validation run. The executable repository remains at `C:\Docker-Projects\Freight-Calc-Nuevo`.

## Documentation authority

The normative sources are:

```text
business_rules/*.md
decisions/functional_decisions.md
docs/adr/*.md
```

Legacy paths under `docs/business rules/` and `docs/decisions/` are compatibility pointers and do not contain independent rules.

## External sources managed by Django

Django Admin currently manages three external files:

```text
product_sth.xlsx -> reference/staging; does not change operational data
stock_sth.xlsx   -> reference/staging; does not change operational data
fuel.csv         -> changes fuel only after Activate
```

The complete `V2026.R2_Unlocked_STH_Freight_Calculator.xlsx` workbook remains a separate import through `import_sth_excel` and the functional source for Excel-vs-Django validation.

See:

```text
docs/04_imports.md
docs/15_admin_configuration_dictionary.md
```

## Users and access - Version 1

The calculator now requires a Django session and uses two roles:

```text
Customer User -> one client only
Internal User -> all clients or selected clients
```

The backend validates the client for the page, products and calculation. Changing `client_code` in the browser does not permit access to another client.

Authorisation and client isolation have passing targeted tests. Complete uniformity of the login rejection message remains open: four `test_login_security` tests document the difference between the expected generic form and the active login view. Do not treat that rule as complete until the code is corrected and all five tests are run.

Django Admin uses:

```text
Administrators       -> Internal User / ALL_CLIENTS / operational Django Admin
Super User           -> native `super` account for setup and recovery
```

After applying migrations:

```powershell
docker compose exec web python manage.py setup_access_roles
```

Create a Customer User:

```powershell
docker compose exec -it web python manage.py create_calculator_user `
  --email customer@example.com `
  --role customer `
  --client STH `
  --set-password
```

Create an Administrator:

```powershell
docker compose exec -it web python manage.py create_calculator_user `
  --email admin@example.com `
  --role internal `
  --all-clients `
  --django-admin `
  --set-password
```

See `docs/05_authentication_integration.md`, `business_rules/users.md` and ADR 0005.

### Primary user groups

```text
Administrators
Customers
Steadfast Users
```

Individual permissions are not edited in Users. They are managed only through Groups. The selected group synchronises the calculator profile, client scope and `is_staff`. The native `super` account does not require a primary group.

## Calculator visual layout - 2026-07-31

The calculator uses a responsive two-column desktop layout:

```text
Route / Shipment / Results | Shipment summary / Calculate freight
```

The refresh is presentation-only. Existing DOM identifiers, JavaScript functions, request payload, API endpoint and calculation services are retained. No staged `Destination / Shipment / Compare rates` navigation or unimplemented quotation controls are included.

## Remembered Fuel source URL - 2026-08-03

`Imports -> External data files -> Fetch fuel from source` exposes an editable HTTP/HTTPS URL. The most recent URL that downloaded and validated successfully is remembered separately for each client through the existing `ExternalDataFile.source_url` history. If no successful history exists, the form uses `FUEL_SOURCE_URL`.

Product and Stock remain local reference-file uploads. Their original filenames and import history are retained, but browsers do not expose or allow Django to prefill the user's local directory.

## Cubic Margin

The calculator provides a web-only `Cubic Margin (%)` field with integer values from 0 to 20. This is an application rule and not an original Excel input.

```text
adjusted visible = ROUND_UP(original visible x (1 + margin/100), 3 decimal places)
adjusted rating  = adjusted visible + internal pallet cubic
```

The default is 0%, so existing Excel-vs-Django batteries do not change. The code contains seven unit tests for 0%, 10%, 20%, rounding and invalid values. A complete Docker run still needs to be captured because the packaged diagnostic did not complete the suite.

## Autocomplete data

Suburb and product autocomplete fields read from PostgreSQL. In an empty database, the container attempts to import the sample workbook after migrations if no suburbs are loaded.

Diagnose first with `showmigrations`, `migrate` and the manual import command. Do not run `docker compose down -v` as the initial solution: it deletes the PostgreSQL volume and all its data. Use it only when deliberately recreating a disposable environment and after confirming that the database does not need to be retained.

<!-- USER_ADMIN_INTEGRATION_0727.0802 -->
## Integrated user administration

User identity and calculator access are managed from **Django Admin > Authentication and Authorization > Users**. See `docs/17_user_admin_runbook.md` and `docs/adr/0006_integrated_user_admin.md`.

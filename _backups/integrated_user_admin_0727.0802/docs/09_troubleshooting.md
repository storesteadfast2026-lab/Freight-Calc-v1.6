# Troubleshooting

## relation "clients_client" does not exist

This error means the PostgreSQL database was started without Django migrations for the project apps.

Safe first fix:

```powershell
docker compose up -d db web
docker compose exec web python manage.py showmigrations
docker compose exec web python manage.py migrate --noinput
```

Then re-run the relevant import and `manage.py check`.

Do not use `docker compose down -v` as the first response. The `-v` option deletes the PostgreSQL volume and its data. Use it only when you intentionally want to recreate a disposable environment and have confirmed that no database data must be retained.

The project includes initial migrations for all custom apps.

## TEAMEX does not match Excel while STEA, COCHRN, and KTI match

Symptom example:

- Excel shows `TEAMEX ROAD` around `$216.76`.
- The application shows `TEAMEX ROAD` around `$197.29`.
- `STEA`, `COCHRN`, and `KTI` match Excel.

Cause:

The issue is not the fuel table if the other carriers match. The previous application logic used a single global weight-break function for all carriers. Excel uses carrier-specific formulas in `BrokerTotals!AI:AO`.

For the Blair Athol test case with SKU 20772 quantity 5 and SKU 20985 quantity 5, the chargeable weight is 2075 kg. Excel resolves `TEAMEX ROAD` to `WeightBrk = 3`; the old global function resolved it to `WeightBrk = 4`.

Fix included in this version:

- `TEAMEX` now uses the `BrokerTotals` TEAMEX break logic only for `TEAMEX`.
- `TFMX`, `TEAMTAS`, `MACHIPE`, and `MIPEC` have separate selectors.
- Carriers without a break formula, such as `STEA`, `COCHRN`, and `KTI`, use blank `WeightBrk`.

After deploying the code change, rebuild/restart the web container:

```bash
docker compose up -d --build web
```

Reimporting the Excel workbook is not required for this specific code fix, as long as the current `RATES` data is already imported correctly.

## Many false failures after switching validation batteries

Symptom:

```text
Workbook import skipped. Using current PostgreSQL data.
Cases run: 20
OK rows: 36
FAIL rows: 61
```

or many carriers fail with small percentage differences even though recent targeted/random tests passed.

Cause:

The expected CSV files and PostgreSQL data are likely from different Excel baselines. For example, running `live_latest` expected CSVs while PostgreSQL is still loaded with `random_current` data can produce false failures.

Fix:

Import and validate in the same command using the matching workbook:

```bash
docker compose exec web python manage.py validate_excel_battery --import-workbook --workbook /app/sample_data/live_baselines/<matching-baseline>.xlsx --replace --cases <matching-cases.csv> --expected <matching-outputs.csv> --components <matching-components.csv> --report <report.csv>
```

Rule:

```text
expected CSVs and imported Excel baseline must be generated together
```

## TEAMTAS GENERAL extremely high value

Symptom:

```text
TEAMTAS GENERAL
Excel expected: 828.03
Django actual before fix: 663983.07
```

Cause:

Django was treating `TEAMTAS GENERAL` as a normal kg-based carrier and effectively calculated:

```text
rate * kilograms
```

Excel uses a TEAMTAS-specific formula based on whole tonne/cubic chargeable units plus an extra TEAMTAS fee.

Fix:

`calculator.py` now contains a specific branch for `TEAMTAS GENERAL` that mirrors the workbook row logic.

Historical validation recorded after the fix:

```text
random_current 15 cases: 36 OK / 0 FAIL
live_latest 20 cases: 97 OK / 0 FAIL
```

In the 2026-07-22 review package, only the `live_latest` result remains directly reproducible. The current `random_current` evidence set is incomplete; see `docs/12_validation_findings_log.md`.

## Fetch fuel from source fails

Check that the web container can access HTTPS and resolve DNS:

```powershell
docker compose exec web python -c "from urllib.request import urlopen; print(urlopen('https://www.poscat.com.au/fuelsc/fuel.csv', timeout=30).status)"
```

Also check `.env`:

```text
FUEL_SOURCE_URL=https://www.poscat.com.au/fuelsc/fuel.csv
FUEL_FETCH_TIMEOUT_SECONDS=30
```

A failed fetch does not modify carrier fuel rates. Review:

```text
Django Admin → Audit → Audit events
```

for `FUEL_FETCH_FAILED`.

## Fuel file validates but cannot be activated

Review `Validation summary` for:

- expired dataset;
- missing required columns;
- duplicate `master_rate`;
- no Django ratecards matched;
- identical file already active.

Expired data is blocked unless a superuser supplies a force justification.

## Fuel rates reverted after workbook import

Normal imports use active Admin fuel automatically. Confirm the command did not explicitly use:

```text
--fuel-source workbook
```

To restore the active operational dataset:

```powershell
docker compose exec web python manage.py reapply_active_fuel --client STH
```

Then verify in:

```text
Carriers → Client carrier configs
```

that `Fuel levy source` is `ADMIN_WEB_FETCH` or `ADMIN_UPLOAD`.

## Uploaded files disappear after recreating containers

Confirm `docker-compose.yml` contains:

```yaml
- ./uploaded_data:/app/uploaded_data
```

and that the host folder is writable by Docker Desktop.

## PostgreSQL: `FOR UPDATE cannot be applied to the nullable side of an outer join`

### Symptom

Fuel activation tests or the Admin activation action fail with:

```text
psycopg.errors.FeatureNotSupported:
FOR UPDATE cannot be applied to the nullable side of an outer join
```

### Cause

`activate_fuel_file()` used `select_for_update()` together with
`select_related('fuel_data_file')`. `fuel_data_file` is nullable, so Django
created a `LEFT OUTER JOIN`. PostgreSQL does not permit `SELECT ... FOR UPDATE`
to lock the nullable side of that join.

### Resolution

Lock only rows from `ClientCarrierConfig` and do not join the nullable
`fuel_data_file` relation:

```python
ClientCarrierConfig.objects.select_for_update(of=('self',)) \
    .filter(client=locked_file.client) \
    .select_related('carrier_service__carrier')
```

The code only needs `fuel_data_file_id`, which is available without loading the
related object.

### Verification

```powershell
docker compose exec web python manage.py test apps.imports.tests.test_fuel_import -v 2
```

Expected result:

```text
Ran 6 tests
OK
```

## Product/Stock upload says source products are not in Django

This is a comparison result, not an automatic import failure.

`product_sth.xlsx` and `stock_sth.xlsx` are reference-only sources. Validation compares their normalized SKUs with the operational `Product` table but does not create or modify Products.

Confirm the validation summary contains:

```text
Reference only: Yes
Operational tables updated: No
```

Review source rows in:

```text
Imports → Product source rows
Imports → Stock source rows
```

## Product/Stock upload is detected as duplicate

The SHA-256 hash matches an earlier file for the same client and file type. The current code records a warning and points to the prior file ID; it does not silently merge source rows into operational data.

## Product/Stock Admin buttons are missing

Confirm migration and active code/template:

```powershell
docker compose exec web python manage.py showmigrations imports
docker compose exec web python manage.py check
```

Expected migration:

```text
[X] 0003_product_stock_reference_sources
```

Then rebuild/restart the web service:

```powershell
docker compose up -d --build web
```

## Calculator authentication appears enabled but the page is still public

`CALCULATOR_REQUIRE_AUTH=1` currently affects only the middleware check for `/api/` paths. It does not protect `/` and does not authenticate a Django user.

Do not treat `ExternalAuthMiddleware` as complete login. Implement the session-based access plan in `docs/16_user_access_review_and_plan.md`.

## Staff user can access more Admin operations than expected

Several custom import actions and read-only Admin views currently rely broadly on `is_staff`. Until explicit action/model permissions are added, grant `is_staff=True` only to fully trusted operational administrators.

## User access troubleshooting — 2026-07-22

### Calculator redirects to login

Expected for anonymous users. Create a profile-backed user and sign in at `/accounts/login/`.

### HTTP 403: no calculator access profile

The Django user exists but does not have `CalculatorUserProfile`, or `calculator_access` is disabled.

### HTTP 403 when changing client

Expected when the requested client is outside the user's single/selected scope. Do not fix this by trusting the browser value; correct the profile assignment.

### Staff user receives HTTP 403 in Django Admin

A normal administrator must meet all conditions:

```text
is_staff=True
Internal User
ALL_CLIENTS
calculator_access=True
member of Django Administrator
```

Run `setup_access_roles`, then create or correct the user through a Technical Superuser.

### setup_access_roles reports missing permissions

Run migrations first:

```powershell
docker compose exec web python manage.py migrate
docker compose exec web python manage.py setup_access_roles
```

### User cannot log in after command creation

Without `--set-password`, the command intentionally creates an unusable password. Set one securely:

```powershell
docker compose exec -it web python manage.py changepassword user@example.com
```

## Login shows plain text: `This user does not have a calculator access profile`

### Cause

An existing Django account successfully authenticated but had no enabled `CalculatorUserProfile`. The original calculator decorator returned `HttpResponseForbidden`, which caused the browser to show the exception text on an otherwise blank page.

### Resolution — 2026-07-24

- `CalculatorLoginView` checks calculator entitlement before creating the session.
- The calculator decorator clears old unauthorized sessions.
- The user returns to the normal login card with a generic access message.
- Internal profile details are no longer shown as a plain browser response.

### Verification

```powershell
cd C:\Docker-Projects\Freight-Calc-Nuevo

docker compose exec web python manage.py test `
  apps.authentication_gateway.tests.test_login_flow `
  apps.freight.tests.test_user_access `
  -v 2
```

Expected manual result:

```text
Valid password + no calculator profile
→ remain on login screen
→ show: Your account does not have access to the Freight Calculator.
→ no active authenticated session
```

## Logout displays Django CSRF debug page

### Cause

The logout form was submitted from a stale tab, a rotated session token, or a different host such as switching between `localhost` and a LAN IP.

### Resolution — 2026-07-24

The application keeps CSRF protection enabled but renders front-end CSRF failures with the login-card visual presentation. It does not add `csrf_exempt` and does not silently accept an invalid token.

Use one host consistently during a browser session:

```text
http://localhost:8000
```

or:

```text
http://192.168.16.120:8000
```

## Login card fades in at the centre instead of moving down from above

### Cause

The approved source used `fadeInDown` on the complete wrapper and delayed `fadeIn` classes on the logo and fields. A generic replacement kept only opacity animation on elements already positioned in the centre.

### Resolution — 2026-07-24

- `registration/login.html` again uses `login-wrapper fadeInDown`.
- `static/css/login.css` contains the isolated approved animation.
- The visual change does not alter login, CSRF, messages, user profiles or client authorization.
- The incorrect mobile rule `width: 400%` from the old standalone CSS was not copied; the corrected width is responsive.

After deployment rebuild the web image and force-refresh the browser:

```powershell
cd C:\Docker-Projects\Freight-Calc-Nuevo
docker compose up -d --build web
```

Then use `Ctrl + Shift + R` in the browser.

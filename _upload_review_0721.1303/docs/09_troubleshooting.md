# Troubleshooting

## relation "clients_client" does not exist

This error means the PostgreSQL database was started without Django migrations for the project apps.

Fix:

```bash
docker compose down -v
docker compose build --no-cache
docker compose up
```

If you do not want to remove the database volume, run:

```bash
docker compose exec web python manage.py migrate --noinput
```

The project now includes initial migrations for all custom apps.

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

Validation after fix:

```text
random_current 15 cases: 36 OK / 0 FAIL
live_latest 20 cases: 97 OK / 0 FAIL
```

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

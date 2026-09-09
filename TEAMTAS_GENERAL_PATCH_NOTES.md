# TEAMTAS GENERAL patch notes

This patch updates `app/apps/freight/services/calculator.py` to replicate Excel `BrokerTotals` row 20 for `TEAMTAS GENERAL`.

Evidence:

- Case: `RANDOM_004`
- Destination: `WEEGENA TAS 7304`
- SKU: `BRH4443`
- Quantity: `2`
- Excel expected: `TEAMTAS GENERAL = 828.03`
- Old Django actual: `663983.07`

Root cause:

The previous Django formula used `per_kg * kg` for all carriers. For `TEAMTAS GENERAL`, Excel uses whole tonne/cubic units:

```text
AF20 = ROUNDUP(MAX(CalcLines!P29 * cubic_conversion, CalcLines!O29 / 1000), 0)
H20  = Basic * (CalcLines!P29 * cubic_conversion)
L20  = ROUNDUP(MAX(Minimum, H20 + Subsequent + Rate * AF20), 2)
AW20 = (pallet_count * 2) + (visible_cubic * 0.6)
```

For the failing case:

```text
rating_cubic = 3.741
visible_cubic = 3.701
actual_weight_kg = 3565
AF20 = 4
rate = TEAMTASGENERALLZ21STHP
base = 821.81
AW20 = 6.2206
final display = 828.03
```

Validation commands:

```powershell
docker compose exec web python -m py_compile `
  /app/apps/freight/services/calculator.py
```

```powershell
docker compose exec web python manage.py validate_excel_battery `
  --cases /app/apps/freight/fixtures/random_current/sth_excel_random_cases.csv `
  --expected /app/apps/freight/fixtures/random_current/sth_excel_random_outputs.csv `
  --components /app/apps/freight/fixtures/random_current/sth_excel_random_components.csv `
  --case-id RANDOM_004 `
  --report /app/reports/random_current/sth_excel_random_004_report.csv
```

```powershell
Import-Csv .\reports\random_current\sth_excel_random_004_report.csv |
  Group-Object row_type,overall_status |
  Format-Table Count, Name
```

Then run the full `random_current` and `live_latest` batteries.

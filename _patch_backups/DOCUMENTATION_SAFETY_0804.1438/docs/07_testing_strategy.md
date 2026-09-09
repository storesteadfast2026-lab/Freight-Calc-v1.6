# Testing Strategy

Required regression tests against Excel:

- suburb/state/postcode lookup
- SKU dimension lookup
- SKU mode consolidation
- manual mode consolidation
- pallet weight addition
- pallet cubic addition
- tailgate YES
- tailgate NO / hand unload
- zone lookup
- rate lookup key
- fuel surcharge
- final total
- result ranking
- cubic margin web-rule validation

Each production release must compare Django outputs against known Excel cases.


## Cubic Margin tests

The current source contains seven `SimpleTestCase` tests in:

```text
app/apps/freight/tests/test_cubic_margin.py
```

They cover 0%, 10%, 20%, upward rounding to three decimals, negative values, values above 20 and decimal percentages. Because Cubic Margin is not an Excel input, these are application-rule tests. Every release must also rerun the normal 0% Excel-vs-Django batteries to prove the extension did not alter the baseline calculation path.

The uploaded diagnostic did not complete the Django suite, so record the actual Docker result before marking the tests as executed.
## Excel vs Django validation batteries

The project uses Excel-generated expected outputs to validate Django independently.

Current battery types:

| Battery | Purpose | Fixture path | Report path |
|---|---|---|---|
| `live_latest` | Stable real 20-case regression battery | `app/apps/freight/fixtures/live_latest/` | `reports/sth_excel_live_comparison_report.csv` |
| `random_current` | Replaceable random exploratory battery | `app/apps/freight/fixtures/random_current/` | `reports/random_current/sth_excel_random_comparison_report.csv` |

Current evidence in the 2026-07-28 review package:

```text
live_latest
Cases available: 20
Expected output rows available: 77
Component rows available: 20
Included report rows: 97
OK rows: 97
FAIL rows: 0

random_current
Cases available: 5
Expected outputs: missing
Components: missing
Matching Excel baseline: missing
Comparison report: missing
Current reproducible status: NOT CONFIRMED
```

A previous documented run recorded 15 random cases and 36 OK rows. Treat that as historical evidence only until a complete fixed-folder `random_current` set is regenerated and committed together. Legacy `random_5` and `random_30` folders remain in the supplied tree but must not be used for new runs.

## Validation rules

- Excel `Calculator` is the visual source of truth for expected ranked outputs.
- `CalcLines` may be used for diagnosis, but it must not replace `Calculator` as the visible expected output.
- `Calculator!J24` is visible cubic.
- `CalcLines!P29` is rating cubic and may include pallet cubic.
- Expected CSV files must be used with the exact Excel baseline that generated them.
- Each meaningful calculation fix should be validated with both `live_latest` and at least one random or targeted battery.

## Recommended next battery

Create a targeted battery for special carrier rules:

```text
targeted_special_rules
```

Priority coverage:

- `TEAMTAS GENERAL`
- `TEAMEX` overlength
- `TFMX ROAD` weight breaks
- `COCHRN ROAD`
- `CUST COLLECT`
- pallet-only, carton-only, and mixed P/C shipments
- postcodes shared by multiple suburbs

## Authentication and authorization tests — 2026-07-22

Added test modules:

```text
apps.authentication_gateway.tests.test_access
apps.authentication_gateway.tests.test_commands
apps.freight.tests.test_user_access
```

They cover customer isolation, selected/all internal scope, administrator requirements, group creation, user creation, anonymous HTTP behavior and tampered `client_code` rejection.

Required Docker command:

```powershell
docker compose exec web python manage.py test apps.authentication_gateway apps.freight apps.imports -v 2
```

These tests must pass together with the existing calculation and import tests. Authentication changes do not replace Excel-vs-Django validation because they do not validate freight formulas.

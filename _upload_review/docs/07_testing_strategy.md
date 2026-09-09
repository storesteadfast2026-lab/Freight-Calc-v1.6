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

Each production release must compare Django outputs against known Excel cases.

## Excel vs Django validation batteries

The project uses Excel-generated expected outputs to validate Django independently.

Current battery types:

| Battery | Purpose | Fixture path | Report path |
|---|---|---|---|
| `live_latest` | Stable real 20-case regression battery | `app/apps/freight/fixtures/live_latest/` | `reports/sth_excel_live_comparison_report.csv` |
| `random_current` | Replaceable random exploratory battery | `app/apps/freight/fixtures/random_current/` | `reports/random_current/sth_excel_random_comparison_report.csv` |

Current confirmed results:

```text
live_latest real 20-case battery
Cases run: 20
Expected output rows loaded: 77
Report rows: 97
OK rows: 97
FAIL rows: 0

random_current 15-case battery
Cases run: 15
Expected output rows loaded: 21
Report rows: 36
OK rows: 36
FAIL rows: 0
```

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

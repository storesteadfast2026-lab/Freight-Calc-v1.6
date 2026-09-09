# Excel-Django Validation Strategy

## Purpose

The application migrates freight calculation logic from the STH Excel workbook to Django. The validation strategy keeps Excel and Django independent:

1. Django or CSV fixtures provide input cases.
2. Excel calculates expected outputs using the official workbook.
3. Django calculates the same cases using imported PostgreSQL data.
4. `validate_excel_battery` compares Excel expected outputs against Django actual outputs.

The goal is not simply to make tests pass. The goal is to prove that Django reproduces Excel behavior for each documented scenario.

## Official source of truth

The official base workbook is:

```text
sample_data/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx
```

The customer-visible expected ranked outputs must come from the `Calculator` sheet.

Important distinction:

| Excel area | Meaning | How it is used |
|---|---|---|
| `Calculator` | customer-visible inputs and outputs | source of truth for expected ranked outputs |
| `CalcLines` | internal calculation details | diagnostic support only |
| `BrokerTotals` | carrier row formulas | source for reverse-engineering carrier logic |
| `RATES`, `ZONES`, `FuelSurcharge`, `SettingFlags` | imported data / configuration | imported into PostgreSQL |

## Battery types

### live_latest

Stable 20-case real regression battery.

```text
app/apps/freight/fixtures/live_latest/
reports/sth_excel_live_comparison_report.csv
```

Current confirmed result:

```text
Cases run: 20
Expected output rows loaded: 77
Report rows: 97
OK rows: 97
FAIL rows: 0
```

### random_current

Replaceable random exploratory battery. This folder is intentionally reused and overwritten for new random checks.

```text
app/apps/freight/fixtures/random_current/
reports/random_current/sth_excel_random_comparison_report.csv
```

Current confirmed 15-case result:

```text
Cases run: 15
Expected output rows loaded: 21
Report rows: 36
OK rows: 36
FAIL rows: 0
```

## Baseline pairing rule

Every battery has two inseparable parts:

1. CSV expected files generated from Excel.
2. Excel baseline workbook imported into PostgreSQL.

They must come from the same generation run.

Do not compare expected CSV files from one baseline against PostgreSQL data imported from another baseline.

## What a report row means

`Report rows` is not the number of cases.

Example:

```text
20 input cases
77 ranked carrier output rows
20 component total rows
97 report rows total
```

## Component totals

The battery compares component totals separately from carrier ranked outputs. This matters because Excel may generate no carrier for a case while still showing total weight/cubic components.

When no carrier is generated, Django uses `consolidate_lines()` as a fallback for component comparison.

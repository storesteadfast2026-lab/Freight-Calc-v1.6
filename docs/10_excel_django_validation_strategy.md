# Excel-Django Validation Strategy

## Purpose

The application migrates freight calculation logic from the STH Excel workbook to Django. The validation strategy keeps Excel and Django independent:

1. Django or CSV fixtures provide input cases.
2. Excel calculates expected outputs using the official workbook.
3. Django calculates the same cases using imported PostgreSQL data.
4. `validate_excel_battery` compares Excel expected outputs against Django actual outputs.

The goal is not simply to make tests pass. The goal is to prove that Django reproduces Excel behaviour for each documented scenario.

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

Evidence classification for the package generated on 2026-08-18:

```text
Fixtures and passing comparison report retained: YES
Matching Excel baseline retained: NO
SHA-256 pairing manifest retained: NO
Historical result confirmed by included report: YES
Full run reproducible from this package alone: NO
```

### random_current

Replaceable random exploratory battery. This folder is intentionally reused and overwritten for new random checks.

```text
app/apps/freight/fixtures/random_current/
reports/random_current/sth_excel_random_comparison_report.csv
```

Historical documented result:

```text
Cases run: 15
Expected output rows loaded: 21
Report rows: 36
OK rows: 36
FAIL rows: 0
```

This historical result is not reproducible from the 2026-08-18 review package. The package contains only `sth_excel_random_cases.csv` with 5 cases under `random_current`; the matching outputs, components, Excel baseline and report are absent. Regenerate all four artifacts together before calling the current random battery passing.

The only supported random workspace is `random_current`. Do not create or use `random_5`, `random_10`, `random_30` or similar folders for future runs; legacy folders in the repository should be treated as deprecated evidence.

## Baseline pairing rule

Every battery has two inseparable parts:

1. CSV expected files generated from Excel.
2. Excel baseline workbook imported into PostgreSQL.

They must come from the same generation run.

Do not compare expected CSV files from one baseline against PostgreSQL data imported from another baseline.

The baseline filename and SHA-256 should be retained with the fixture hashes in
a manifest. Do not select a workbook merely because it is the newest file in
`sample_data/live_baselines/`.

For `live_latest`, the runbook writes:

```text
reports/sth_excel_live_latest_manifest.csv
```

## Database-isolation rule

`validate_excel_battery --import-workbook --replace` invokes
`import_sth_excel --replace`. It therefore rebuilds client calculation data and
deletes non-Fuel `ExternalDataFile` records in the selected database. Batteries
must run against a dedicated temporary PostgreSQL database, not the operational
database used by the calculator.

Use `--fail-on-difference` for release validation. Without it, the command can
write `FAIL` rows to the CSV report but still return exit code zero.

The exact PowerShell procedure is maintained in
`docs/11_validation_runbook.md`.

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

## Fixed random_current contract

Use only these directories:

```text
app/apps/freight/fixtures/random_current/
generated_excel_baselines/random_current/
sample_data/live_baselines/random_current/
reports/random_current/
```

Use only these published CSV names:

```text
sth_excel_random_cases.csv
sth_excel_random_outputs.csv
sth_excel_random_components.csv
sth_excel_random_comparison_report.csv
```

The cases, outputs, components, report and Excel baseline form one versioned evidence set even though the directory names remain fixed.

# ADR 0008 - Validation CSVs must stay paired with their Excel baseline

## Status

Accepted

## Context

The project uses generated CSV files as expected outputs for batteries such as `live_latest` and `random_current`. PostgreSQL data is imported from an Excel workbook/baseline.

A false failure scenario occurred when expected CSV files and imported PostgreSQL data came from different baselines.

## Decision

Every validation battery must keep these artifacts paired:

1. generated cases CSV
2. generated outputs CSV
3. generated components CSV
4. generated Excel baseline workbook imported into PostgreSQL

Validation should prefer `--import-workbook` so the import and comparison happen in the same command.

## Consequences

- Do not run a battery against whatever PostgreSQL data happens to be loaded unless you know it is the matching baseline.
- When refreshing a battery, refresh all CSVs and the baseline together.
- False FAIL rows caused by baseline mismatch should not trigger calculation patches.

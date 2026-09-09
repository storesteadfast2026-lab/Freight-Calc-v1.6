# ADR 0014 — Isolated database for Excel validation batteries

- **Status:** Accepted.
- **Date:** 2026-08-04.

## Context

`validate_excel_battery --import-workbook --replace` calls
`import_sth_excel --replace`. For the selected client, that import rebuilds
Products, Rates, Zones, carrier configuration and tailgate data. It also
deletes non-Fuel `ExternalDataFile` records; Product/Stock staging rows are
deleted by cascade.

The validation command writes FAIL rows but returns a non-zero exit code only
when `--fail-on-difference` is present.

Running the previous documented command through `docker compose exec web`
therefore risked changing operational data and could produce a false-positive
automation result.

## Decision

1. Create a uniquely named PostgreSQL database for each Excel validation run.
2. Run migrations and `validate_excel_battery` through an ephemeral web
   container configured with that database.
3. Require `--fail-on-difference` for release validation.
4. Keep CSV expected files paired with the exact baseline and retain their
   SHA-256 values.
5. Remove only the uniquely named validation database after preserving the
   report.

## Consequences

- Operational Product, Product/Stock import history and Fuel configuration are
  not changed by regression batteries.
- A completed battery has a meaningful process exit code for automation.
- Validation setup takes one additional database-creation and migration step.
- The exact PowerShell commands are maintained in
  `docs/11_validation_runbook.md`.

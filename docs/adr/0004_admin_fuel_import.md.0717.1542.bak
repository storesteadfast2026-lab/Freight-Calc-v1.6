# ADR 0004: Operational fuel rates are activated from Django Admin

- **Status:** Accepted
- **Date:** 2026-07-17

## Context

The Excel workbook downloads `fuel.csv` through Power Query and uses `master_rate` to populate `FuelSurcharge!K`. Django previously imported only the cached workbook result, creating a dependency on opening, refreshing and saving Excel before import.

## Decision

Django becomes the operational owner of fuel-rate ingestion:

```text
official fuel.csv
→ manual Admin fetch/upload
→ validation and preview
→ explicit activation
→ ClientCarrierConfig.fuel_levy
```

The calculation formula is unchanged.

The workbook value remains only for:

- initial legacy bootstrap when no Admin dataset is active;
- historical Excel baseline validation.

Normal workbook imports must preserve and reapply the active Admin fuel dataset.

## Safety controls

- immutable stored file snapshot;
- SHA-256;
- required-column and value validation;
- transaction-based activation;
- expiry blocking;
- duplicate detection;
- rollback with mandatory reason;
- read-only audit history;
- explicit source provenance on each carrier config.

## Consequences

- Excel no longer needs to be refreshed to update production fuel.
- Docker requires persistent upload storage and outbound HTTPS access.
- historical validation must use workbook fuel from the matching baseline;
- operational and historical fuel contexts are deliberately separated.

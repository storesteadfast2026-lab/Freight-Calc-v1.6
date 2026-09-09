# ADR 0016 — FTP Fuel source adapter

Date: 2026-08-27
Status: Accepted for phase 1

## Context

Fuel data will arrive through the existing FTP-mounted `uploaded_data` folder.
The source schema differs from the previously validated Admin Fuel CSV. The
freight calculation engine and existing Fuel activation/rollback behaviour are
already validated and must not be rewritten to understand the FTP format.

## Decision

Introduce a source adapter at the import boundary. The adapter recognises the
FTP schema, normalises percentage surcharge values to the decimal representation
already used by Django, and cross-checks Rate Card/carrier relationships against
Django configuration. `PRICE` is the only supported FTP Fuel type in phase 1.

Register FTP snapshots with `source_method=FTP_DROP`. The validation command is
idempotent by SHA-256 and does not activate rates. Existing manual activation,
transaction, audit and rollback services are reused after validation.

## Consequences

- FTP-specific fields do not enter `FreightCalculatorService`.
- Historical Admin Fuel CSVs remain supported.
- A source-format change fails safely rather than being guessed.
- Carrier data provides an independent cross-check instead of being ignored.
- Automation can later call the same validation service without redesigning the
  business calculation layer.

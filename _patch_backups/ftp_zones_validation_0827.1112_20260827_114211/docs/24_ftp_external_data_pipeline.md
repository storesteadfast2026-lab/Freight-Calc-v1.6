# FTP External Data Pipeline

Status: Phase 1 implemented for Fuel only.
Date: 2026-08-27.

## Purpose

External files are deposited in the existing FTP-mounted `uploaded_data`
directory. The ingestion layer must protect the validated freight calculator
from malformed or mismatched source data without moving FTP-specific behaviour
into the calculation engine.

## Architectural boundary

```text
FTP / uploaded_data
        |
        v
source snapshot + SHA-256
        |
        v
source-format adapter
        |
        v
existing Django validation / staging
        |
        v
manual activation (phase 1)
        |
        v
existing operational models
        |
        v
existing FreightCalculatorService
```

`apps.freight.services.calculator` must not read FTP files and must not contain
FTP format rules.

## Fuel phase 1

Sample received on 2026-08-27:

- 21 data rows;
- 21 unique `rate_no` values;
- required columns: `rate_no,carrier,name,surcharge,type`;
- all sample rows use `type=PRICE`;
- all sample surcharge values are numeric.

The sample is evidence for the current source shape, not a hard-coded list of
allowed carriers or Rate Cards. The validator derives expected client/carrier
relationships from Django.

### Source-to-Django mapping

| FTP field | Meaning in ingestion | Operational destination/check |
|---|---|---|
| `rate_no` | Rate Card identifier | `ClientCarrierConfig.ratecard` |
| `carrier` | Independent source carrier | must match Django carrier for a used Rate Card |
| `name` | description | retained as source information |
| `surcharge` | percentage | divide by 100 before `fuel_levy` |
| `type` | interpretation mode | phase 1 supports `PRICE` |

### Safety decisions

- FTP arrival alone never activates Fuel in phase 1.
- The source drop is never deleted by the validation command.
- Django stores a versioned snapshot and SHA-256.
- Reprocessing identical content is idempotent.
- Used Rate Card + wrong carrier is blocking.
- Used Rate Card + unsupported type is blocking.
- Unused external Rate Cards are reported, not treated as errors merely because
  the source is broader than STH.
- Existing Admin Fuel activation, transaction, audit and rollback mechanisms
  are reused.
- No freight pricing formula is changed.

## Future files

Postcodes, Zones and Products will reuse the pipeline after Fuel has been
operationally proven. Their schemas and cross-file validation rules must be
implemented independently; the Fuel implementation must not be copied blindly
because their cardinality and business relationships differ.

## Phase 1 review output - 2026-08-27

The FTP Fuel validation command exposes the operational comparison directly in
the terminal. For every client configuration matched by Rate Card and Carrier,
it reports the current database Fuel levy, the normalised incoming levy and
whether activation would CHANGE or leave the value UNCHANGED.

Client configurations absent from the source are listed separately with the
action `PRESERVE EXISTING`. This is intentional: absence from a broader external
source must not silently zero or overwrite an established client configuration.

An identical previously validated source is idempotent. No new snapshot is
created and the saved validation summary is reused for review. This behaviour
keeps repeated operational checks cheap and traceable.

## Phase 2 - FTP postcodes validation - 2026-08-27

`uploaded_data/postcodes.csv` is the next controlled source after Fuel. Phase 2 starts as validation-only. The command snapshots the source, records SHA-256 provenance, validates schema and row identity, compares the candidate Australian postcode set with the current global `locations.Suburb` table, and stops before any database mutation.

Source schema: `index, suburb, state, postcode`. The source `index` is validated as `suburb + state + postcode`; Django continues to use its existing `normalized_key = state + suburb`, so the external source index is not copied into that field.

Rows outside the eight Australian state/territory codes or using postcode `0000` are explicitly shown as excluded candidates. Existing Django suburb rows missing from the source are reported and preserved in Phase 2. No delete or replace behaviour is implemented yet.

## FTP postcodes cross-validation review - 2026-08-27

The postcodes pipeline now has a second read-only review gate after schema/delta validation. Prospective new suburb rows are checked against current Django `FreightZone` records and existing `Suburb` aliases/postcodes.

The intended future activation policy is add-only. Exact zone-backed rows may become activation candidates; likely spelling aliases, conflicting postcodes, and rows without exact zone evidence stay in manual review. The FTP source file is not deleted, SHA-256 idempotency is unchanged, and no operational `Suburb` row is changed during validation.

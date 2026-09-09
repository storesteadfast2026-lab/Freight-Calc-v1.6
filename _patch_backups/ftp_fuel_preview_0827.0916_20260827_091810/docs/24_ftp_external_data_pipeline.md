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

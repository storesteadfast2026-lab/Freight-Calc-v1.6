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

The seven Cubic Margin tests are included in the 63-test calculator UI
regression run recorded on 2026-07-31. Continue recording each new Docker run;
historical success is not a guarantee for later source changes.

## Excel vs Django validation batteries

The project uses Excel-generated expected outputs to validate Django independently.

Current battery types:

| Battery | Purpose | Fixture path | Report path |
|---|---|---|---|
| `live_latest` | Stable real 20-case regression battery | `app/apps/freight/fixtures/live_latest/` | `reports/sth_excel_live_comparison_report.csv` |
| `random_current` | Replaceable random exploratory battery | `app/apps/freight/fixtures/random_current/` | `reports/random_current/sth_excel_random_comparison_report.csv` |

Retained evidence from the review package generated on 2026-08-18:

```text
live_latest
Cases available: 20
Expected output rows available: 77
Component rows available: 20
Included report rows: 97
OK rows: 97
FAIL rows: 0
Matching baseline included: no
Fixture/baseline SHA-256 manifest included: no
Fully reproducible from this package: no

random_current
Cases available: 5
Expected outputs: missing
Components: missing
Matching Excel baseline: missing
Comparison report: missing
Current reproducible status: NOT CONFIRMED
```

A previous documented run recorded 15 random cases and 36 OK rows. Treat that as historical evidence only until a complete fixed-folder `random_current` set is regenerated and committed together. Legacy `random_5` and `random_30` folders remain in the supplied tree but must not be used for new runs. The old TEAMTAS case `WEEGENA / BRH4443 x 2` is not part of the current five-case file.

All Excel-vs-Django batteries that import with `--replace` must use an isolated
PostgreSQL database. The validation command must include
`--fail-on-difference`; otherwise report rows may contain `FAIL` while the
process still returns a successful exit code.

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

## Authentication and authorisation tests — 2026-07-22

Added test modules:

```text
apps.authentication_gateway.tests.test_access
apps.authentication_gateway.tests.test_commands
apps.freight.tests.test_user_access
```

They cover customer isolation, selected/all internal scope, administrator requirements, group creation, user creation, anonymous HTTP behaviour and tampered `client_code` rejection.

Required Docker command:

```powershell
docker compose exec web python manage.py test apps.authentication_gateway apps.freight apps.imports -v 2
```

These tests must pass together with the existing calculation and import tests. Authentication changes do not replace Excel-vs-Django validation because they do not validate freight formulas.

## Current source test inventory — reviewed 2026-08-18

Static test discovery in the current source contains:

```text
72 test methods total
10 Fuel import tests
6 Product/Stock import tests
5 login-security tests
```

The 63-test UI regression was executed before the four additional remembered
Fuel URL tests and intentionally excluded `test_login_security`. Four of the
five login-security tests remain documented known failures. The latest
`TEST_RESULTS.txt` attempted the complete suite but stopped while creating
`test_freight_platform`; it is not evidence that all 72 tests ran or passed.
Do not describe the complete suite as runtime verified until a new full output
is retained.

## FTP Fuel validation tests - 2026-08-27

The FTP Fuel adapter is covered separately from freight formula testing.

Static discovery after this patch contains 25 tests in `apps.imports`: 19 Fuel tests (10 existing + 9 FTP Fuel tests) and 6 Product/Stock tests. Runtime success must still be confirmed in Docker.
Required automated checks include:

- FTP schema detection;
- `surcharge` percentage-to-decimal normalisation;
- Rate Card/carrier cross-validation against `ClientCarrierConfig`;
- rejection of a carrier mismatch on a used Rate Card;
- rejection of unsupported `type` on a used Rate Card;
- warning-only handling of unrelated Rate Cards;
- validation does not modify operational Fuel;
- explicit activation retains the existing transaction/rollback path and
  records `FTP_DROP` provenance;
- snapshot creation preserves the FTP source and is idempotent by SHA-256;
- `process_uploaded_fuel` validates only and never activates rates.

Run the import-module regression after every FTP Fuel change:

```powershell
docker compose exec -T web python manage.py test apps.imports --noinput -v 2
```

Then run the full Django regression suite for a release candidate:

```powershell
docker compose exec -T web python manage.py test --noinput -v 2
```

The Excel-vs-Django freight battery is not required merely because fresh Fuel
data arrived. It is required when a freight calculation rule changes or when a
new Excel baseline is intentionally refreshed with the same external data as
Django. This avoids comparing a historical Excel Fuel value with a newer FTP
Fuel value and incorrectly treating the expected data difference as a code
failure.

## FTP Fuel preview regression - 2026-08-27

The FTP Fuel management-command tests now verify that validation output contains
the matched configuration preview (`Current Fuel -> New Fuel`), identifies
client configurations missing from the source, preserves their existing values,
and can re-display an already validated identical snapshot without creating a
new snapshot or activating Fuel.

For a functional Fuel-source change, the minimum automated gate is:

1. `python manage.py check`
2. `python manage.py makemigrations --check --dry-run`
3. `python manage.py test apps.imports --noinput -v 2`
4. `python manage.py test --noinput -v 2` before first operational activation

## FTP postcodes regression - 2026-08-27

Postcodes Phase 2 adds tests for schema, source-index integrity, duplicate rejection, leading-zero preservation, invalid/non-Australian candidate exclusion, legitimate multiple postcodes for one suburb/state, idempotent FTP snapshots, delta preview, and the invariant that validation never mutates the operational Suburb table.

This change does not touch freight calculation logic, FreightZone, FreightRate, Product or Fuel activation logic.

## FTP postcodes cross-validation regression - 2026-08-27

Targeted tests cover exact FreightZone evidence, likely alias detection, postcode conflicts, read-only behaviour, and re-validation of an existing Phase 1 snapshot when its stored summary predates cross-validation. Imports regression remains the mandatory test gate for this patch; the full Django suite can be run separately after the operational postcodes activation design is approved.

## FTP Zones validation regression - 2026-08-27

Automated coverage for the Zones validation adapter includes required schema, index/index2 contracts, exact duplicate reporting, preservation of raw short Australian postcodes for review, Suburb-reference review, existing-vs-add delta classification, ambiguous carrier-service mapping, snapshot/SHA idempotency, source preservation, and proof that the management command does not modify operational `FreightZone` data.

## Zones rate-driven service mapping regression - 2026-08-27

Zones import regression must prove that: one source row can expand to multiple configured services when each has a matching FreightRate zone; only rate-applicable services are selected; no matching service rate becomes `REVIEW_NO_RATE_ZONE`; validation remains idempotent and read-only; and service names are never hard-coded into the importer.

## Zones field-diagnostic regression - 2026-08-27

Regression coverage now verifies that candidate changes are classified by routing field (`ZONE`, `SUBZONE_ONLY`, `AREA_ONLY`, `SUBZONE_AND_AREA`) and that current non-exact rows are split between routing-detail differences at source-present locations and locations absent from source. All tests remain validation-only and assert that operational `FreightZone` rows are not modified.

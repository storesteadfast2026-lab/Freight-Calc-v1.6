# FTP Postcodes import

## Purpose

`postcodes.csv` is imported as a controlled, additive source for the global Australian suburb lookup used by the Freight Calculator.

The operational policy is **ADD ONLY / PRESERVE EXISTING**. An external Postcodes source may add a suburb/state/postcode triplet that does not already exist, but it must never update, rename or delete an existing `Suburb` row as part of the routine import workflow.

## Provenance

The verified initial Django `Suburb` baseline was imported from the workbook `SUBURBS` worksheet. Existing rows therefore retain their historical workbook provenance unless they are known from a prior FTP Postcodes activation.

FTP source provenance is tracked through `ExternalDataFile`, SHA256 snapshots, validation summaries, import summaries and audit events. The operational `Suburb` model is deliberately kept simple and is not expanded with provenance fields in this phase.

For each source snapshot, validation reports:

- existing rows confirmed in the current source;
- new rows eligible for ADD;
- existing rows not present in the current source, which are explicitly preserved;
- excluded invalid source rows;
- possible alias/spelling observations as diagnostic information only.

Alias diagnostics never rewrite source values and never block an otherwise valid new row.

## Validation rules

The expected source columns are:

`index, suburb, state, postcode`

Validation requires:

- non-blank required fields;
- `index` equal to `suburb + state + postcode` after case normalisation;
- no duplicate source indexes or duplicate suburb/state/postcode triplets;
- Australian state codes only for activation candidates;
- four-digit numeric postcodes other than `0000`;
- preservation of leading zeroes such as `0820` and `0870`.

Rows outside the Australian candidate rules are reported as excluded. Validation does not alter the operational `Suburb` table.

## Activation

Activation is explicit and transactional.

For every valid source triplet:

- if it already exists, it is preserved unchanged;
- if it does not exist, it is created with origin recorded in the import summary as `FTP_POSTCODES`.

Existing rows that are absent from the current source remain in Django and are reported as `PRESERVE EXISTING`.

No FreightZone evidence is required to add a valid Postcodes source row. FreightZone is a routing domain, not the authority for geographic validity.

## Rollback

Rollback can remove only rows that were created by the specific active Postcodes activation being rolled back. It can never remove a row that existed before that activation.

Rollback is blocked if a created row is now referenced by operational `FreightZone` data. This is an impact protection check only; FreightZone is not used to validate or approve Postcodes source rows.

A rollback reason is mandatory and is stored in the audit trail.

## Current analysed source snapshot

The source analysed before this implementation had SHA256:

`9fe1cf42cedf68eba4b80dc27d131d8dde11b3dc7f753c8adfdcfd50fa4160c9`

Observed at analysis time:

- 18,097 source rows;
- 18,095 valid Australian rows;
- 2 excluded rows;
- 18,079 rows already in the verified workbook/Django baseline;
- 16 source rows not yet in Django;
- 3,075 existing workbook/Django rows not present in the current source and therefore preserved.

These counts are evidence for that snapshot, not hard-coded import rules.

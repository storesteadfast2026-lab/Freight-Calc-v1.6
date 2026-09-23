# Product rejected-row bulk review — 0911.1516

## Scope

This incremental update improves the existing controlled review of malformed
`products.csv` rows. It does not import or modify operational `Product` data.

## Changes

- Adds one review screen for all rejected rows in a validated Product source.
- Shows the complete proposed name, description and comment with wrapping text.
- Shows dimensions, cubic, quantity, weight, pallet and source status at a glance.
- Supports search and filtering by review status.
- Supports individual checkboxes and `Select all visible`.
- `Save selected proposals` and `Approve selected` affect checked rows only.
- Requires a common review note before bulk approval.
- Makes selected-row processing atomic: one failure rolls back the complete
  selected batch.
- Keeps `Edit` collapsed unless a row needs correction.
- Keeps the individual `Details` page available.
- Keeps `Product source rejected rows` hidden from the Imports main menu.
- Introduces a reusable bulk-review workflow with a Product-specific adapter.

## Safety

- Approved repairs create `ProductSourceRow` reference staging records only.
- Operational Product, freight type, rates, zones and Calculator remain unchanged.
- Existing per-row audit events continue to record reviewer, note and approved data.
- No database migration is included.

## Verification

- 18 Product/Stock source tests passed.
- 115 Imports application tests passed.
- Python compilation and template parsing passed.

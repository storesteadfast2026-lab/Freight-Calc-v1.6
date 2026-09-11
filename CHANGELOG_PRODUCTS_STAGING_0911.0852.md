# Products CSV staging — 2026-09-11 08:52 ACST

## Approved scope

This increment adds controlled validation and staging for `products.csv`.
It does not create, update, deactivate or delete operational `Product` rows and
does not change P/C, Stock, freight rates or calculator logic.

## Delivered

- Product upload accepts `products.csv`; legacy Product XLSX remains supported.
- CSV decoding supports UTF-8 and CP1252.
- The required 13-column structure is validated before field mapping.
- Structurally malformed, value-invalid and normalised-duplicate rows are
  isolated in the read-only `ProductSourceRejectedRow` table.
- Valid rows remain in `ProductSourceRow` even when rejected rows exist.
- The validation summary reports dimension completeness and comparisons with
  the current operational Product catalogue.
- A downloadable CSV report contains valid/rejected rows, differing fields,
  source values and current operational dimensions, weight and cubic.
- Audit metadata continues to state `operational_tables_updated=False`.

## Validation against the supplied products.csv

| Check | Result |
|---|---:|
| Source rows | 38,646 |
| Valid staging rows | 38,611 |
| Rejected rows | 35 |
| Structurally malformed rows | 21 |
| Duplicate rows after SKU normalisation | 14 (7 SKU pairs) |
| Complete dimensions | 10,504 |
| Zero/missing dimensions | 28,097 |
| Partial dimensions | 10 |
| Operational Products before validation | 232 |
| Operational Products after validation | 232 |
| Operational Product data unchanged | Yes |

The four operational SKU not represented by a valid source row are `20985`,
`J301-8000000`, `NEW` and `SM440-A RAL5002`. SKU `20985` is present in a
malformed source row; the other three are absent from the supplied CSV.

## Test evidence

- Django system check: passed.
- Migration drift check: passed (`No changes detected`).
- Imports application: 106 tests passed.
- Full application suite: 178 tests passed; 4 pre-existing login-security
  assertions failed. The known login defect is already recorded as
  `AUTH-LOGIN-001` and is outside this increment.

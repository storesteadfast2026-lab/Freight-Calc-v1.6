# Product rejected-row review — 0911.1337

## Added

- Editable reconstruction proposal for malformed `products.csv` rows.
- Separate `Save proposal only` and `Approve into staging` actions.
- Mandatory review note for approval.
- Link from an approved rejection to its `ProductSourceRow` staging record.
- Audit events for saved and approved repair decisions.
- Dynamic pending, approved and effective-valid staging counts.
- Protection against in-place revalidation after a repair review begins.
- Controlled rollback cleanup for proposals and staging rows created by an
  approved repair.
- Regression coverage for Translogis product `4307`, preserving the meaningful
  trailing inch quote in `CaravanSpareWheelCover13"` while separating its full
  description correctly.

## Menu change

- `Product source rejected rows` is hidden only from the main Imports menu.
- Rejected rows remain accessible from `External data files` through
  `Review rejected rows` for the selected Product source.

## Safety boundary

- No repair action creates or updates operational `Product` records.
- No repair action changes freight type, rates, zones, carriers, fuel or
  Calculator results.

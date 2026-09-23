# Product reconciliation 0914.1324

Adds the first read-only reconciliation step after all rejected Product rows
have been approved into staging.

- Compares effective `ProductSourceRow` data against operational `Product`.
- Reports same, different, source-only, operational-only and duplicate SKU.
- Highlights zero source dimensions and dimension, weight and cubic differences.
- Shows source quantity/comments and preserves operational C/P as read-only.
- Blocks reconciliation while any rejected row remains pending.
- Supports search, status filters and 100-row pagination.
- Does not add an Apply action and does not update Calculator or Product.

No database migration is included.

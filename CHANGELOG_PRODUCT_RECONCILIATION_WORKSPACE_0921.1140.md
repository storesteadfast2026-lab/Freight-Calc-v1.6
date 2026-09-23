# Product Reconciliation Workspace 0921.1140

## Added

- grouped Product comparison queue for rapid review;
- bulk draft decisions for selected rows or an active group;
- individual field-level editing with optional custom values;
- client-scoped reusable rules for future Product uploads;
- proposed-result preview with remaining warnings;
- audit records for draft and rule operations;
- dedicated Django permission for reconciliation management.
- updated `setup_access_roles` grants the required draft/rule permissions to
  the existing Administrators group.

## Safety boundary

This release stores review decisions only. It does not update operational
`Product`, Calculator, rates, zones or C/P. The source `pallet` value is
informational and never changes freight type automatically.

## Database

Migration `imports.0012_product_reconciliation_workspace` adds
`ProductReconciliationDecision` and `ProductReconciliationRule`.

## Verification

- Django system check passes;
- all 132 Imports tests pass, including five new workspace tests;
- the real legacy `products.xls` is accepted by the Product File Adapter and
  builds a reference-only workspace without operational table updates.

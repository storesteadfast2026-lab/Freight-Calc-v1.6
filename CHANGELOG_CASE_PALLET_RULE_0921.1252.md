# Case/Pallet Reconciliation Rule 0921.1252

## Updated decision

The Product reconciliation workspace now uses the current Chat.Calc rule:

- `pallet = 0` proposes freight type `C` (Case);
- `pallet > 0` proposes freight type `P` (Pallet);
- missing, negative or non-numeric values require manual review.

## Workspace changes

- source pallet and proposed C/P are shown beside the Calculator value;
- C/P differences and invalid pallet values have dedicated review groups;
- bulk presets can include the derived C/P proposal;
- individual review supports a manual `C` or `P` selection;
- reusable rules retain the C/P field-level decision;
- preview shows the proposed C/P.

## Safety boundary

The result remains a reconciliation draft. This update does not add an
operational Apply action and does not update `Product.freight_type`, Calculator,
rates or zones.

## Verification

- Django system check passes;
- no database migration is required;
- all 138 Imports and access-role tests pass.

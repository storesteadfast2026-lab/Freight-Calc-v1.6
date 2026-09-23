# Reconciliation Edit Visibility 0921.1326

## Updated interface

- moved `Edit product` from the clipped far-right action column into the SKU
  column;
- kept Select and SKU/Edit columns visible during horizontal scrolling;
- increased the SKU column width so the action remains readable;
- linked each Edit action directly to the individual editor;
- removed the unused final table column.

## Included business rules

This patch is based on Case/Pallet Rule 0921.1252 and retains the current
Chat.Calc decisions:

- `pallet = 0` proposes `C`;
- `pallet > 0` proposes `P`;
- invalid pallet values require manual review;
- decisions remain drafts and do not update operational Products.

## Verification

- Django system check passes;
- all 139 Imports and access-role tests pass;
- an automated UI test verifies that `Edit product` is visible beside the SKU
  and targets the individual editor.

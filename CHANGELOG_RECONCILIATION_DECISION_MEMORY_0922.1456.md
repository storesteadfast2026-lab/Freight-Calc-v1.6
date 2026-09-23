# Freight Calculator v1.6 — Reconciliation Decision Memory 0922.1456

## Added

- Product reconciliation remembers each successfully applied, approved
  solution by client, SKU and exact Source fingerprint.
- An exact repeated problem prepares the approved solution as a new draft.
- A changed Source for the same SKU shows a warning and previous solution but
  never selects it automatically.
- Selected rows can explicitly reuse a previous solution.
- Administrators can adopt current Calculator values as memory with a mandatory
  reason.
- Previously applied decisions are backfilled without changing Products.
- Repeated Product files are identified by SHA-256.
- Memories are visible and can be deactivated in Django Admin with audit.
- Apply and rollback record or reverse their corresponding memory changes.

## Safety

Reconciliation memory cannot update operational Products. A remembered
solution remains a draft until it has been reviewed in Preview and explicitly
applied. Existing Product Apply protections and rollback remain in force.

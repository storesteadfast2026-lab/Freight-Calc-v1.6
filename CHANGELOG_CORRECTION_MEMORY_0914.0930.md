# Correction memory and field-level errors — 0914.0930

## Included

- Corrects the misleading bulk error produced when only the common review note
  was missing.
- Shows the exact row, field and validation message for genuine invalid values.
- Opens invalid edit panels automatically and highlights the row and field.
- Adds links from the error summary to the affected field.
- Adds generic, client-scoped external-data correction memory.
- Reuses the approved proposal only when the original source content is an
  exact fingerprint match.
- Flags the same record key as changed when its source content differs.
- Adds a correction-memory filter and audit event.
- Backfills memory from Product repairs approved before migration 0011.

## Safety boundary

- A memory match never approves a row automatically.
- A review note and explicit selection remain required for every new upload.
- Batch approval remains atomic.
- Only `ProductSourceRow` staging may be changed by this workflow.
- Operational `Product`, Calculator, rates, zones and freight type remain
  unchanged.

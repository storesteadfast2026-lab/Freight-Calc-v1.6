# ADR 0017 — Current Product Workflows and Evidence Boundaries

**Date:** 2026-10-02  
**Status:** Current implementation record and documentation reconciliation; installed runtime verification pending.

## Context

The baseline `Calculator_App_AI_Continuity_20261002_113659_907.zip` implements workflows that several earlier documents describe as absent or reference-only. A code snapshot does not prove installed database state. Existing documents must be supplemented without discarding their historical content or changing application code.

## Record of current implementation

1. Customer and Client remain distinct. `Customer.linked_client` connects the commercial and technical identities. Product identity is Client + SKU. The atomic Customer enabling service preserves an existing Client name and excludes special Customer `*`.
2. Global Product Master upload/validation/preview resolves ownership through Customer and the linked Client. It retains four ownership states and bridges authorised Product work to existing reconciliation staging. ExternalDataFile retains its mandatory single-Client owner.
3. Product review contains field decisions, memory, Draft, Preview, initial Apply, audit batches and Correction Rounds. Draft/Preview do not mutate Product. Source-only uses explicit creation through the existing Apply service, with transactional locking and Product identity constraints.
4. Physical differences remain distinct from review status. Keep Calculator may resolve review while leaving the physical mismatch. Invalid/zero source dimensions remain subject to eligibility rules.
5. Stock remains reference staging; global operational aggregation, availability and zero/missing-stock rules are not implemented or confirmed.
6. Saved Estimates includes authorised recipient resolution and PDF email delivery code. This extends the email exclusion in ADR 0015; its non-binding-estimate and no-quotation-lifecycle boundaries remain valid.

## Explicit documentation precedence

| Earlier statement | Current clarification | Canonical reference |
| --- | --- | --- |
| DEC-007 Product reference-only | Validation is reference-only; explicit Product Apply exists | DEC-022, PROD-010 |
| Additional CUSTOMER dimension in `docs/Work_Calc_Update_Standard_0924.0804.md` | Product identity is Client + SKU | DEC-023, PROD-008 |
| Sources described only as single-Client files | Independent global Product Master exists; single-Client sources remain | DEC-024, PROD-009 |
| ADR 0015 / DEC-021 exclude email | PDF email exists; quotation lifecycle remains excluded | DEC-026 |
| Historical LATEST snapshot descriptions | Shared-script policy requires a single timestamped historical ZIP | DEC-027 |
| Pending notes suggest Stock semantics | Proposals are not approved rules or implemented availability | DEC-025, PROD-012 |

This ADR supplements the prior records for these subjects only. It does not rewrite their original dates, claim new calculation validation or authorise unknown Stock semantics.

## Implementation evidence

Paths below are relative to the application baseline:

- `app/apps/clients/calculator_customer_enable.py`, models and enabling tests.
- `app/apps/products/models.py` and identity migrations/tests.
- `app/apps/imports/services/product_master.py` and `admin_product_master.py`.
- `app/apps/imports/services/product_reconciliation_apply.py`, workspace, memory and Correction Rounds services.
- Imports migrations `0012_product_reconciliation_workspace.py`, `0013_product_reconciliation_apply.py`, `0014_product_correction_rounds.py`, `0016_productmaster.py`.
- Product Master, bridge, operational status, reconciliation and Stock source tests in `app/apps/imports/tests/`.
- `app/apps/imports/services/stock_source.py` records `reference_only`.
- `app/apps/saved_estimates/services/emailing.py` and PDF export service.

## Open defects and decisions

- Initial Product UPDATE rollback restores earlier values without comparing the post-Apply snapshot against current values; later edits can be overwritten. CREATE rollback has snapshot/reference checks. Do not advertise uniform rollback safety.
- Legacy `import_sth_excel` creates Client through `get_or_create`; `--replace` and Docker bootstrap require review. The global Product Master path does not create Customers/Clients.
- CalculatorAuthenticationForm is not integrated into the active login view in the audited baseline.
- BFT needs full operational acceptance, including rates and authorised calculation; historical counts are not current DB evidence.
- Stock snapshot completeness, repeated rows, serials, negatives, quantity aggregation, absent SKUs and zero stock remain open.
- Excel equivalence, PostgreSQL concurrency and SMTP/FTP need current execution evidence.

## Verification boundary

The preceding audit reported five Product adapter tests passing, inventory integrity and Python syntax checks. It did not run the complete Django suite or confirm the installed Windows/PostgreSQL environment. This documentation-only delivery does not repeat those tests or add runtime evidence. Migration files show intended schema evolution, not applied migration state.

Use `IMPLEMENTED` for demonstrated code, `RUNTIME_VERIFIED` only for a specific executed behaviour, and distinguish PARTIAL, PENDING, BLOCKED, DOCUMENTED_ONLY and CONFLICTING_DOCUMENTATION as appropriate. Never elevate historical test logs or Product counts to current runtime facts.

## Consequences

The two canonical documents retain all previous content and gain dated clarifications. This ADR is additive. No application code, migrations, data, configuration or remote Git state is changed. Replacing these documents does not install application fixes or settle unresolved business decisions.

> Current-state supplement — 2026-10-02. The original document below is retained in full. For the subjects explicitly clarified in the dated supplement at the end, use that supplement rather than the older wording. This is a documentation update; it neither changes application behaviour nor certifies the installed database or deployment.

# Business Rules — Products

**Status:** CONFIRMED where explicitly stated; calculation-sensitive items remain PENDING Excel validation  
**Last review:** 2026-07-28  
**Canonical location:** `business_rules/products.md`

## PROD-001 — Operational product source

The calculator uses Django `Product` rows as the operational SKU master. For STH, the full workbook import maps the Excel `SKUs` sheet into client-scoped Product rows.

## PROD-002 — Client isolation

A Product is unique by `client + sku`. Product lookup and calculation must use the server-authorised client.

## PROD-003 — Confirmed product fields

The operational model stores:

```text
sku
name
description
length_m
width_m
height_m
weight_kg
cubic_m3
freight_type
active
source_row
```

The imported freight type is reduced to its first character and currently supports:

```text
P = Pallet
C = Case/Carton
```

## PROD-004 — Reference-only Product and Stock files

`product_sth.xlsx` and `stock_sth.xlsx` uploaded through Django Admin are reference/staging sources. Their validation must not update operational Product, FreightRate, FreightZone or ClientCarrierConfig rows.

## PROD-005 — Consolidation evidence

Product dimensions, weight, cubic and freight type feed freight-line consolidation. The exact behaviour for mixed P/C shipments, quantities greater than one and overlength remains subject to directed Excel-vs-Django cases.

## PROD-006 — Change control

Do not change product-derived calculation behaviour only to satisfy a Django test. A calculation change requires:

1. a confirmed Excel input/output case;
2. the matching Excel baseline;
3. a Django comparison report;
4. updates to the calculation flow, traceability matrix and validation findings log.

## PROD-007 — ProductKitComponent Admin visibility

`ProductKitComponent` is an initial compatibility model for the workbook
`SKU-Kits` concept. No current calculation, import, view or service references
this model. It is therefore not exposed in Django Admin.

The model, database table, migration and any existing records are retained.
This is a visibility decision only and does not prove that kit expansion is
implemented.


---

## Current product and stock rules — 2026-10-02

**Evidence baseline:** `Calculator_App_AI_Continuity_20261002_113659_907.zip`.
**Status:** implemented in source unless explicitly identified as pending; runtime acceptance remains separate.
**Technical reconciliation:** `docs/adr/0017_current_product_workflows_and_evidence.md`.

### PROD-008 — Customer and Calculator Customer identities

`Customer` is the commercial Customer; `Client` is the technical Calculator Customer. `Customer.linked_client` connects them. Operational Product identity remains **Client + SKU**, as stated in PROD-002. The same SKU may exist for different Clients. Do not add a redundant `Product.customer_code` identity dimension.

Enabling an existing Customer must reuse or create its Client through `apps/clients/calculator_customer_enable.py`. An existing Client retains its name. The special `* / All Customers` Customer cannot become a Calculator Customer. Product Master imports must not create Customers or Clients automatically.

**Known legacy exception:** `apps/imports/management/commands/import_sth_excel.py` still uses `Client.objects.get_or_create()` and supports `--replace`. The intended no-automatic-creation rule is therefore not enforced across every legacy import path. This supplement records that gap; it does not approve or correct it.

### PROD-009 — Global Product Master and single-Client sources

The global `products.xls` workflow is independent: **Upload → Validate → Preview**. Resolve each row through `CUSTOMER → Customer.code → Customer.linked_client`. Keep `LINKED`, `UNLINKED`, `UNKNOWN_CUSTOMER` and `EMPTY_CUSTOMER` distinct. Unknown or unlinked ownership is not permission to create or guess an owner.

`ExternalDataFile.client` remains mandatory for the single-Calculator-Customer workflow. Do not make it nullable or use `*` as an artificial owner for the global master.

### PROD-010 — Validation, review and explicit Apply

PROD-004 remains valid for upload and validation: these actions do not mutate operational Product or tariff/configuration tables. Its reference-only wording does **not** exclude the subsequent Product reconciliation Apply implemented in the current baseline.

Source rows remain immutable. Save Draft and Preview do not update Product. Operational changes require an explicit authorised Apply through the existing staging, decisions, memory, audit/history and rollback services. Reuse the existing workflow rather than adding a parallel import or reconciliation module.

Decisions are per field. A Dimensions decision must not silently change Weight, Cubic or other fields. Preserve bulk/inline review and `SOURCE_DIMENSIONS_ZERO` handling. Review status is separate from physical differences: Keep Calculator may be Applied/Resolved while a physical difference remains. Distinguish Needs review, Draft, Partially reviewed and Applied/Resolved.

Correction Rounds are implemented, including further controlled corrections after an initial Apply. Their existence does not mean all rollback paths have equivalent protections.

### PROD-011 — Source-only creation

Reuse the existing Product Master bridge to staging and Preview → Apply/Create. Preview creates no operational Products. Apply creates only still-missing, eligible Products for the authorised Calculator Customer; it must not update, delete or move existing Products in this creation workflow.

Preserve source conversions, Weight/Cubic, field validation and audit/history. The implemented PALLET mapping is zero → C, positive → P; new Products use `active=True`. Staged and global eligible selections exist in the current workflow. Apply uses transactions and locking, alongside Product identity constraints. PostgreSQL concurrency behaviour still requires execution evidence.

After an import, rebuild Source-only and counters and discard the old pagination position. Ineligible rows remain pending. Historical STH values of 372 operational Products and 44 blocked Source-only rows are not current verified quantities.

### PROD-012 — Product versus Stock authority

The calculator currently uses operational Product attributes. Stock validation stores reference rows, including quantity, serial/location and physical values, but does not establish an operational global Stock Master or update Product from Stock.

The following remain **pending business confirmation and implementation**: global Stock resolution through Customer links, quantity aggregation, availability, zero stock and treatment of absent SKUs. Do not assume missing SKU means zero stock, that one row equals one bike/unit, or that quantities should be summed without confirming repeated rows, serials and snapshot semantics. Negative quantities and full versus partial snapshots also need confirmation.

Stock physical values must not silently override Product dimensions, Weight or Cubic. No Stock availability restriction is currently established in the calculation engine.

### PROD-013 — Authorisation and rollback limits

All searches, comparisons, IDs, direct requests and Apply actions must use server-authorised Client scope. A global source does not grant access to other Calculator Customers. Reuse SINGLE_CLIENT, ALL_CLIENTS and SELECTED_CLIENTS.

Initial Product Apply rollback exists. For CREATE it checks the saved post-Apply snapshot and references before deletion. Its UPDATE branch currently restores the earlier snapshot without an equivalent post-Apply comparison, risking loss of later changes. This is an open implementation defect, not a confirmed safe-rollback guarantee.

### Evidence references and limits

- `app/apps/clients/models.py`, `calculator_customer_enable.py` and its tests.
- `app/apps/products/models.py` and identity migrations/tests.
- `app/apps/imports/services/product_master.py`, `product_reconciliation_apply.py`, `product_reconciliation_workspace.py`, `product_correction_rounds.py`, `product_reconciliation_memory.py`, `stock_source.py`.
- `app/apps/imports/admin_product_master.py`, associated templates and Product Master/reconciliation tests.
- Imports migrations `0012`, `0013`, `0014` and `0016` describe schema evolution, not proof that migrations are applied in the installed database.

The preceding audit reported five Product file-adapter tests passing and Python syntax/inventory checks. The full Django suite and installed Windows/PostgreSQL runtime were not verified. Do not treat historical test reports, quantities or pending notes as current runtime evidence.

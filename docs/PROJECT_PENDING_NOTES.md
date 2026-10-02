# Calculator App — Pending Items & Observations

**Purpose:** Persistent project register for pending work, observations, risks and decisions that must not depend on ChatGPT conversation memory.

**Recommended project location:** `C:\Docker-Projects\Freight-Calc-v1.6\PROJECT_PENDING_NOTES.md`

**Maintenance rule:** Update this file whenever a new pending item, risk, decision or follow-up is identified. Keep completed items in the table and change their status to `COMPLETED` rather than deleting them, so the project retains a simple audit trail.

## Status values

- `PENDING` — identified but not yet analysed or implemented.
- `ANALYSIS` — under investigation.
- `READY` — solution agreed and ready to implement.
- `IN PROGRESS` — implementation underway.
- `BLOCKED` — waiting on data, infrastructure or another dependency.
- `COMPLETED` — implemented and verified.

## Pending items / observations

| ID | Area | Status | Priority | Observation / Pending Item | Expected Outcome / Acceptance Criteria | Test / Example | Notes |
|---|---|---|---|---|---|---|---|
| PEND-001 | Products / Calculator Customer onboarding | PENDING | HIGH | Define and verify the complete flow for enabling a new Customer from the global `products.xls` Product Master as a Calculator Customer and making its Products operational in Calculator App. The Product Master already contains Products for Customers that are not yet linked. Creating/linking the Calculator Customer alone must not be assumed to make those Products operational. | A new Customer can be enabled as a Calculator Customer, its Product Master rows become eligible for that Calculator Customer, the rows can be reconciled safely against its operational Product set, eligible Products can be Previewed/Applied, and the resulting active Products are selectable and usable in Calculator App. Existing Customer isolation/authorisation must be preserved. | Use `BFT` / **Best Business** as the next onboarding test after STH. The current Product Master validation shows **620 BFT source rows**; verify Customer → Calculator Customer link, the exact BFT reconciliation states, eligible/blocked Products, Preview/Apply, active Product count and Calculator product selection. | Reuse the existing Customer → linked Calculator Customer flow and Product Master reconciliation/import logic. Do not create a second Product import system. Confirm what happens immediately after linking BFT before applying any Products. |

| PEND-002 | Stock Master / global Customer distribution | ANALYSIS | HIGH | Define the global `stock.xls` import architecture. The source contains Stock for multiple Customers and must be distributed through `Customer → linked Calculator Customer`, rather than uploaded as a separate customer-specific stock file. Preserve source rows and aggregate operational availability by Calculator Customer + SKU. | `stock.xls` can be uploaded once globally; rows resolve safely to the correct Calculator Customer; STH/BFT and other Customers remain isolated; quantity can be reconciled/applied without changing Product dimensions, weight, cubic, freight type or ownership. | Start with STH. Compare the global stock source with the legacy workbook `StockImported` and operational Products. Later repeat with BFT once BFT is enabled as a Calculator Customer. | Legacy workbook analysis shows Stock was used for quantity/In Stock plus weight/cubic comparison, not directly by the freight calculation formulas. Confirm whether the new App should only preserve this behaviour or introduce an explicit availability rule. |
| PEND-003 | Stock source semantics | PENDING | HIGH | Confirm whether `stock.xls` is a complete current-stock snapshot and confirm the exact meaning of `quantity`, repeated SKU rows, serial rows and missing SKUs. Do not interpret absence as zero stock until this is confirmed. | Documented source authority and aggregation rules: repeated SKU handling, zero/negative quantity handling, missing SKU semantics, and whether serial rows should be retained as detail only. | Validate against Translogic Stock screen/export for selected STH SKUs with multiple serial rows and quantities. | Required before any Apply/operational Stock update is enabled. |

## Suggested verification checklist for PEND-001

1. Confirm `BFT` exists in the Customer master and record its current `linked_client` state.
2. Confirm the number of `products.xls` rows owned by `BFT` and check for duplicate `CUSTOMER + SKU` pairs.
3. Enable/link BFT as a Calculator Customer using the existing supported flow.
4. Verify that BFT Product Master rows become `LINKED`/eligible for BFT reconciliation, but are **not automatically written into operational Product** records merely because the Customer was enabled.
5. Run BFT Product reconciliation and record:
   - Source rows
   - Operational Products
   - Same
   - Different
   - Source only
   - Operational only
   - Eligible
   - Blocked
   - Duplicate source
   - Invalid source rows
6. Preview eligible Source-only Products before Apply.
7. Apply only through the existing controlled Product import workflow.
8. Confirm new operational Products are created with the correct Calculator Customer (`Client`) and `active=True`.
9. Confirm those Products appear in Calculator App product search/autocomplete when BFT is the active Calculator Customer.
10. Confirm no BFT Product is visible to STH and no STH Product is exposed to BFT.
11. Run at least one end-to-end freight calculation for BFT after Products are available.
12. Create a manual Continuity Snapshot using `05_Create_Continuity_Snapshot.bat` after the onboarding test is completed and verified.

## Decisions / Principles to retain

- `products.xls` is a **global Product Master**, not a single-Customer file.
- `CUSTOMER` in `products.xls` is used to resolve Product ownership through `Customer → linked Calculator Customer`.
- Operational Product identity remains `Calculator Customer + SKU` (`Product.client + Product.sku`).
- Linking a Customer as a Calculator Customer must **not silently create or overwrite operational Products**.
- Product creation/update must remain controlled through reconciliation / Preview / Apply.
- Customer isolation and authorisation must remain intact.

## Completed items

| ID | Area | Status | Outcome |
|---|---|---|---|
| DONE-001 | Products / STH | COMPLETED | Current STH Product scope closed: 372 operational and active Products; 44 Source-only Products remain blocked by incomplete/non-positive source dimensions; no eligible Products remain pending import. |
| DONE-002 | Continuity Snapshot | COMPLETED | `04_Verify_Update.bat` performs Verify only. `05_Create_Continuity_Snapshot.bat` manually creates the timestamped Continuity Snapshot and updates `Calculator_App_Continuity_LATEST.zip`. |


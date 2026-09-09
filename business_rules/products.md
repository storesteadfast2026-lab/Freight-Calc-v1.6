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

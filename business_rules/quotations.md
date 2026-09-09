# Business Rules — Quotations

**Status:** QUOTATIONS PENDING; SAVED ESTIMATES IMPLEMENTED  
**Last review:** 2026-08-24  
**Canonical location:** `business_rules/quotations.md`

## Current boundary

The delivered project has no persistent Quotation model and no binding quotation lifecycle.

The separate `saved_estimates.SavedEstimate` model stores verified freight-estimate snapshots. A saved estimate:

- is created manually after a successful calculation;
- is recalculated and verified by the server before persistence;
- retains all returned carrier options;
- is printable through browser print/PDF;
- can be duplicated by an Internal User;
- can be exported to CSV or Excel by Internal Users;
- remains an estimate and is not a binding quotation.

## Prohibited assumption

Do not infer quotation permissions from saved-estimate permissions. A Customer User can create and view their own saved estimates for the assigned Client, but this does not grant quotation creation or approval rights.

## Required evidence before implementation

A future quotation specification must define and approve at least:

1. persistent model and identifiers;
2. client ownership and user visibility;
3. draft/final/cancelled states;
4. recalculation and rate-snapshot behaviour;
5. PDF and email rules;
6. audit retention;
7. authorisation tests and migrations.

Until that specification is accepted, binding quotation functionality remains outside the implemented scope. Saved Estimates are governed by `docs/23_saved_estimates_module.md` and ADR 0015.

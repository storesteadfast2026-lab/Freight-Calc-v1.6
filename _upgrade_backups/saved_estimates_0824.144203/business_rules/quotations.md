# Business Rules — Quotations

**Status:** PENDING  
**Last review:** 2026-07-28  
**Canonical location:** `business_rules/quotations.md`

## Current boundary

The delivered project has no persistent Quotation model. Therefore, no quotation lifecycle, ownership, client visibility, draft/final status, PDF generation or email-delivery rule is approved or implemented.

## Prohibited assumption

Do not infer quotation permissions from calculator roles. In particular, statements that a Customer User can create or view quotations are not current Version 1 rules.

## Required evidence before implementation

A future quotation specification must define and approve at least:

1. persistent model and identifiers;
2. client ownership and user visibility;
3. draft/final/cancelled states;
4. recalculation and rate-snapshot behaviour;
5. PDF and email rules;
6. audit retention;
7. authorisation tests and migrations.

Until that specification is accepted, quotation functionality remains outside the implemented scope.

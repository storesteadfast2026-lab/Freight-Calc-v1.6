# ADR 0015 — Isolated Saved Estimates Module

**Status:** Accepted  
**Date:** 2026-08-24

## Context

Users require saved freight estimates, history, print/PDF, internal export and duplication. The existing freight calculation is validated against Excel behaviour and must not be changed by persistence work.

## Decision

Implement persistence in the new `apps.saved_estimates` Django app.

- The freight engine remains authoritative and unchanged.
- Saving performs a second server-side calculation through the existing public service.
- A record is created only when the browser result and server result match.
- Input and result snapshots use an explicit schema version.
- The migration is additive.
- Object visibility follows calculator role and Client scope.
- Customers see only records they created.
- Tabular exports are Internal-User-only.
- A feature flag can remove all Saved Estimates UI and endpoints without disabling the calculator.

## Consequences

- Saving costs one additional calculation request, but does not add work to normal calculations.
- Historic records preserve the values shown at creation time when current rates later change.
- Future snapshot formats can be added by incrementing `schema_version`.
- The module can be modified independently as long as its bridge continues to honour the FreightRequest and FreightResult contract.

## Exclusions

- Saved estimates are not binding quotations.
- No email delivery, approval lifecycle or draft/final/cancelled workflow is introduced.
- No calculation formula, rate lookup, Fuel, Tailgate, zone or consolidation rule is changed.


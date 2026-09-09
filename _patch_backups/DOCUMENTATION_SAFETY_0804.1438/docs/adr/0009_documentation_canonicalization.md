# ADR 0009 — Canonical documentation structure

- **Status:** Accepted.
- **Date:** 2026-07-28.

## Context

The review package contained competing copies of user rules and functional decisions, placeholder Product/Rate/Quotation documents, duplicate document number 17, duplicate ADR number 0002 and duplicate decision number DEC-012. Some older copies described quotation permissions that are not implemented.

## Decision

Use these canonical locations:

```text
business_rules/*.md
decisions/functional_decisions.md
docs/00...19 numbered documents
docs/adr/0001... uniquely numbered ADRs
```

Historical duplicate locations under `docs/business rules/` and `docs/decisions/` remain as pointer files only. They must not contain independent requirements.

Unverified calculation behavior remains marked `PENDING_EXCEL`, `PARCIAL` or `RIESGO_REVISAR`; documentation finalization must not convert unknown Excel logic into a confirmed rule.

## Consequences

- New work has one authoritative rule and decision source.
- Quotation functionality remains explicitly outside current scope.
- Numbering collisions are removed without discarding historical content.
- Runtime evidence and business-rule certainty remain separate.

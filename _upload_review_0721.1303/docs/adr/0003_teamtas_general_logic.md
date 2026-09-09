# ADR 0003 - TEAMTAS GENERAL uses Excel-specific carrier logic

## Status

Accepted

## Context

A random validation case produced a very large mismatch:

```text
TEAMTAS GENERAL
Excel expected: 828.03
Django before fix: 663983.07
```

The generic carrier calculation used `rate * kilograms`, which does not match Excel for `TEAMTAS GENERAL`.

## Decision

`TEAMTAS GENERAL` has a carrier-specific calculation branch that mirrors the workbook row logic:

- whole tonne/cubic chargeable units
- `Basic * rating_units`
- `Rate * whole_chargeable_units`
- additional TEAMTAS fee based on pallet count and visible cubic

## Consequences

- `TEAMTAS GENERAL` must be included in future targeted regression batteries.
- The generic freight base formula must not be assumed to apply to every carrier.

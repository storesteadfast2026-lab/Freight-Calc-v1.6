# ADR 0001 - Excel is the functional source of truth

## Status

Accepted

## Context

The Django application is a migration of an existing freight calculator workbook. Business rules are embedded across `Calculator`, `CalcLines`, `BrokerTotals`, `RATES`, `ZONES`, `FuelSurcharge`, and `SettingFlags`.

## Decision

The Excel workbook remains the functional source of truth until each rule is explicitly replicated and validated in Django.

Customer-visible expected ranked outputs must come from `Calculator`.

Internal sheets such as `CalcLines` and `BrokerTotals` may be used for diagnosis and reverse-engineering, but they must not replace `Calculator` as the expected visual output.

## Consequences

- Every calculation change should be backed by an Excel-vs-Django validation case.
- Generated expected CSVs must be traceable to the workbook baseline that produced them.

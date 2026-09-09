# System Overview

The application migrates the STH / Steadfast Freight Calculator from Excel to Django/PostgreSQL.

## Excel evidence

The workbook calculation is distributed across:

- `Calculator`: user input and final ranked results.
- `CalcLines`: input consolidation and validation.
- `BrokerTotals`: carrier/service calculation engine.
- `FuelSurcharge`: carrier configuration, fuel and status flags.
- `SUBURBS`: suburb/state/postcode lookup.
- `SKUs`: product dimensions, weight, cubic and freight type.
- `ZONES`: carrier/service zone mapping.
- `RATES`: rate table.
- `SettingFlags`: lists, messages, tailgate and carrier labels.

## Web goal

Build one maintainable, responsive, multi-client freight calculator platform where STH is the first client implementation.

## Current data-loading channels

The project currently has two distinct loading channels:

1. **Full workbook management command**
   - imports the operational base data used by the calculator;
   - supports historical Excel-vs-Django validation;
   - includes products, suburbs, carrier configuration, zones, rates and workbook/bootstrap fuel.

2. **Three Django Admin external sources**
   - `product_sth.xlsx`: validated reference/staging rows only;
   - `stock_sth.xlsx`: validated reference/staging rows only;
   - `fuel.csv`: operational fuel only after explicit activation.

Product and stock source uploads do not update the operational Product, FreightRate, FreightZone or carrier-configuration tables.

## Current authentication boundary

Login and multi-client user scope are web requirements, not Excel logic.

Version 1 now implements:

- Django built-in users and sessions;
- `CalculatorUserProfile` with Customer/Internal roles;
- single, selected and all-client scopes;
- protected calculator page and APIs;
- backend validation of the effective client;
- one minimum `Django Administrator` group plus Technical Superusers;
- explicit permissions for sensitive import actions.

See:

```text
business_rules/users.md
decisions/functional_decisions.md
docs/05_authentication_integration.md
docs/16_user_access_review_and_plan.md
```

## Current web-only calculation extension

`Cubic Margin` accepts a whole percentage from 0 to 20. It adjusts visible/product cubic before rating while leaving pallet cubic separate. It has no confirmed Excel input and defaults to 0, preserving the normal Excel-parity path.

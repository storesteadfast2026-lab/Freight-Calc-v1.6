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

Build a responsive, multi-client freight calculator platform where STH is the first client implementation.

## Important boundary

Login, multi-client administration and FROM address configuration are new web requirements. They are not existing Excel logic.

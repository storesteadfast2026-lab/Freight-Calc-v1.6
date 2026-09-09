# Business Rules — Rates and Zones

**Status:** CONFIRMED where validated; unresolved formulas are explicitly PENDING  
**Last review:** 2026-07-28  
**Canonical location:** `business_rules/rates.md`

## RATE-001 — Operational source

For STH, the full calculator workbook imports operational zone, rate, carrier-configuration, tailgate and workbook/bootstrap fuel data. Product and Stock reference uploads do not change these tables.

## RATE-002 — Zone resolution

Django must resolve a freight zone using `suburb + state` before postcode. Postcode-only fallback must not be used to introduce a carrier alias that Excel would not select, including TEAMEX behaviour.

## RATE-003 — Rate lookup key

The rate lookup uses the Excel-equivalent key components:

```text
carrier/service
zone
subzone
area
WeightBrk
customer code
freight type
```

`WeightBrk` is carrier/service-specific. A single global weight-break formula is not valid.

## RATE-004 — Confirmed carrier-specific branches

The delivered documentation and code contain explicit branches for:

- TEAMEX ROAD / GENERAL;
- TFMX ROAD;
- TEAMTAS GENERAL;
- MACHIPE / MIPEC ROAD.

Other carriers use blank `WeightBrk` unless an Excel formula is confirmed for their active BrokerTotals row.

## RATE-005 — Precision

FreightRate monetary fields use six decimal places in the delivered model. This was introduced to avoid small rate-import differences such as those previously observed for KTI.

## RATE-006 — Fuel provenance

Operational fuel changes only after explicit Admin activation of a validated `fuel.csv`. Historical Excel-vs-Django validation uses workbook fuel from the matching baseline and must restore the active Admin fuel afterward.

## RATE-007 — Pending formulas

The following are not closed business rules and must not be changed without directed Excel evidence:

- exact overlength formula and whether `RATES.overlength_charge`, SettingFlags, or both apply;
- isolated warehouse-handling behaviour;
- hand-unload boundary cases;
- subsequent-unit boundaries;
- mixed pallet/carton rate selection beyond the currently documented behaviour.

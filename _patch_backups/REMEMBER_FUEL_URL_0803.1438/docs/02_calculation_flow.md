# Freight Calculation Flow

1. Receive request.
2. Resolve `suburb + state` to postcode, equivalent to `Calculator!E7`.
3. Build freight lines from SKU mode or manual mode.
4. Consolidate totals like `CalcLines`:
   - total quantity
   - pallets
   - cartons
   - total weight
   - total cubic
5. Apply optional web-only `Cubic Margin` to visible/product cubic and add pallet cubic back unchanged.
6. Apply validation equivalent to `CalcLines!D3:L3`.
7. Iterate over configured carrier/service rows.
8. Resolve zone using `ZONES` equivalent.
9. Calculate chargeable weight: `max(actual weight, cubic * cubic conversion)`, equivalent to `BrokerTotals!AF`.
10. Resolve the `WeightBrk` value using the carrier-specific formulas from `BrokerTotals!AI:AO`.
11. Resolve rate using `RATES` equivalent and the Excel-like key components: carrier, service, zone, subzone, area, `WeightBrk`, customer, and freight type.
12. Calculate base freight.
13. Calculate tailgate or hand unload.
14. Calculate fuel surcharge.
15. Calculate final estimate ex GST.
16. Sort results from cheapest to most expensive.


## Cubic Margin — application-only rule

`Cubic Margin` is not a confirmed Excel rule. It is a web extension applied after line consolidation and before carrier rating.

Input contract:

```text
blank = 0
allowed = whole numbers from 0 to 20
decimals, negative values and values above 20 = validation error
```

Backend formula:

```text
pallet_cubic = pallet_count × 0.02, only when pallet_count > 0.99
visible_cubic = consolidated_rating_cubic - pallet_cubic
adjusted_visible_cubic = ROUND_UP(visible_cubic × (1 + margin_percent/100), 3)
adjusted_rating_cubic = ROUND_UP(adjusted_visible_cubic + pallet_cubic, 3)
```

Example:

```text
Original rating cubic: 4.040
Pallets: 2 → pallet cubic 0.040
Original visible cubic: 4.000
Margin: 10%
Adjusted visible cubic: 4.400
Adjusted rating cubic: 4.440
```

The margin does not change actual weight, pallet count, carton count or maximum length. At 0%, the original consolidated object is preserved, so standard Excel-vs-Django cases remain unchanged. Non-zero margin needs its own web-rule tests rather than being claimed as direct Excel parity.

## Carrier-specific WeightBrk logic

Excel does not use one global weight-break rule for every carrier. `BrokerTotals` defines the break result per carrier row in columns `AI:AO`, and the result is consumed in the rate lookup key.

Implemented carrier-specific selectors:

| Carrier | Service | Excel source | Implemented behavior |
|---|---|---|---|
| `TEAMEX` | `ROAD`, `GENERAL` | `BrokerTotals` rows 13 and 19 | `<751 = 1`, `>751.001 and <1501 = 2`, `>1501.001 and <3001 = 3`, `>3001.001 and <5001 = 4`, `>5000.001 = 5` |
| `TFMX` | `ROAD` | `BrokerTotals` row 15 | `<251 = 1`, `>251.001 and <751 = 2`, `>751.001 and <1501 = 3`, `>1501.001 and <3001 = 4`, `>3001.001 and <5000 = 5`, `>5000.001 = 6` |
| `TEAMTAS` | `GENERAL` | `BrokerTotals` row 20 | `<7.99 = 1`, `>=8 and <12.99 = 2`, `>=13 and <15.99 = 3`, `>=16 and <17.99 = 3`, `>=18 = 5` |
| `MACHIPE` / `MIPEC` | `ROAD` | `BrokerTotals` rows 17 and 21 | `>30 = 2`; otherwise blank |
| Other carriers | Any | no active `BrokerTotals` break formula found for the current rows | blank `WeightBrk` |

This correction fixes the observed TEAMEX mismatch for Blair Athol / SA 5084 with SKU 20772 quantity 5 and SKU 20985 quantity 5. The shipment chargeable weight is 2075 kg; Excel selects TEAMEX break `3`, while the previous global function selected break `4`.

## Regression warning

`BrokerTotals` contains complex carrier-specific formulas. Each carrier-specific branch must be locked against Excel regression cases before production use.

## TEAMTAS GENERAL Excel-specific calculation

`TEAMTAS GENERAL` does not use the generic `Rate * kilograms` calculation.

The workbook logic for `TEAMTAS GENERAL` is based on `BrokerTotals` row 20 and includes these important behaviors:

1. Chargeable units are based on the greater of:
   - rating cubic units: `CalcLines!P29 * cubic_conversion`
   - actual tonnes: `CalcLines!O29 / 1000`
2. The chargeable value is rounded up to a whole unit.
3. The base freight uses TEAMTAS-specific logic:
   - `Basic * rating_units`
   - plus subsequent charge when applicable
   - plus `Rate * whole chargeable unit`
4. Excel also adds a TEAMTAS-specific fee equivalent to:

```text
(pallet_count * 2) + (visible_cubic * 0.6)
```

The visible cubic used in this fee is the customer-visible `Calculator!J24` style cubic, not the internal rating cubic. Since Django consolidation includes pallet cubic, the visible cubic is derived by subtracting pallet cubic:

```text
visible_cubic = rating_cubic - (pallet_count * 0.02)
```

This correction fixed the random validation case:

```text
RANDOM_004
Destination: WEEGENA TAS 7304
Product: BRH4443 x 2
Excel expected: 828.03
Django before fix: 663983.07
Django after fix: matches Excel
```

## Validation baseline alignment rule

A validation battery is only meaningful when the expected CSV files and the imported PostgreSQL data come from the same generated Excel baseline.

Do not mix:

- expected CSVs generated from one Excel baseline
- PostgreSQL imported from another Excel baseline

Mixing them can produce false failures even when the Django calculation logic is correct.

## Fuel data source after Admin import implementation

The calculation formula remains unchanged:

```text
fuel = freight_base × (fuel_levy + extra_surcharge)
```

Only the provenance of `ClientCarrierConfig.fuel_levy` changes.

Operational flow:

```text
fuel.csv from official URL or Admin upload
→ ExternalDataFile validation
→ explicit Admin activation
→ ClientCarrierConfig.fuel_levy
→ FreightCalculatorService
```

Legacy workbook values remain a bootstrap/fixed-baseline mechanism. When an Admin fuel dataset is active, normal workbook imports reapply it after rebuilding carrier configs.

## Authentication boundary — 2026-07-22

Authentication does not alter the freight formula. Before `FreightCalculatorService.calculate()` is called, the web layer resolves an authorized Client from the authenticated user's profile. The service receives that server-approved `client.code` in `FreightRequest.client_code`.

This change must not modify consolidation, zone resolution, rate selection, surcharge, fuel, uprate or display rounding behavior. Existing Excel-vs-Django batteries remain the functional regression authority.

## Product kit model boundary — 2026-07-30

The current calculation flow does not query `ProductKitComponent`. Hiding that
model from Django Admin changes only menu visibility; it does not add, remove or
alter SKU-kit expansion in the calculation.

## Calculator visual-layout boundary — 2026-07-31

The responsive Route, Shipment, Shipment summary and freight-options layout is
a presentation change only. It preserves:

```text
FreightRequest payload keys
/api/calculate/
calculate()
updateProductTotals()
suburb and product autocomplete
server-authorized client resolution
```

Moving `total_weight`, `total_cubic` and the existing Calculate button into the
summary panel does not change how values are derived or sent. `item_count` is a
display-only count of visible shipment rows and is not part of the request.

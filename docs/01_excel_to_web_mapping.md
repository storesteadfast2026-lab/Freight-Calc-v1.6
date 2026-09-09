# Excel to Web Mapping

| Excel | Django equivalent |
|---|---|
| `Calculator!C7` | request.to_suburb |
| `Calculator!D7` | request.to_state |
| `Calculator!E7` | resolved postcode from `Suburb` model |
| `Calculator!E11` | request.tailgate |
| `Calculator!C13` | request.preselect_sku |
| No equivalent Excel input | `FreightRequest.cubic_margin_percent` (`Cubic Margin`, web-only) |
| `Calculator!C15:D22` | selected product lines |
| `SKUs` | `Product` model |
| `SUBURBS` | `Suburb` model |
| `ZONES` | `FreightZone` model |
| `RATES` | `FreightRate` model |
| `FuelSurcharge` | `ClientCarrierConfig` model |
| `SettingFlags!C33:H52` | `CarrierTailgateCharge` model |
| `BrokerTotals!AF` | chargeable weight calculation |
| `BrokerTotals!AI:AO` | carrier-specific `WeightBrk` selector |
| `BrokerTotals!Z` | `FreightResult.estimate_ex_gst` |

## Tailgate

Excel does not assign a unique tailgate value per product. `Calculator!E15:E22` copies the global tailgate flag from `E11`. The cost is calculated at shipment/carrier level using total pallets.

## WeightBrk / rate lookup

The Django rate lookup must not use one global `WeightBrk` formula for all carriers. In Excel, `BrokerTotals!AI:AO` calculates `WeightBrk` differently depending on the carrier row. The code now routes the break calculation by carrier/service before looking up `RATES`.

Observed correction:

| Scenario | Excel behaviour | Previous app behaviour | Corrected app behaviour |
|---|---|---|---|
| `TEAMEX ROAD`, chargeable weight 2075 kg | `WeightBrk = 3` | `WeightBrk = 4` | `WeightBrk = 3` |

Carriers without an Excel break formula for the active `BrokerTotals` row use blank `WeightBrk`, matching the blank `RATES` key used by carriers such as `STEA`, `COCHRN`, and `KTI`.

## Cubic Margin — web-only extension

`Cubic Margin` has no confirmed input cell or business-rule equivalent in the official workbook. It is an application extension. The default value is 0%, preserving the original Excel parity path.

The backend applies the margin only to customer-visible/product cubic, rounds upward to three decimals, and then adds the pallet rating allowance back unchanged. Weight and pallet count are not increased.

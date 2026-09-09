# Calculator UI Design

**Status:** Implemented and validated
**Date:** 2026-08-19
**Scope:** Presentation and browser-side destination binding only

## Approved desktop structure

```text
Navy header: title | user | active client | Sign out

Route                              Shipment summary
Shipment                           Items
Available freight options          Total weight
                                    Total cubic
                                    Calculate freight
```

The staged `Destination / Shipment / Compare rates` progress strip is not part
of the approved current design.

## Destination selector behaviour

The Route card exposes one visible destination control: `To Suburb`. Each
autocomplete option and the selected value use the complete Australian location
label:

```text
ADELAIDE, SA 5000
```

The browser retains the selected values separately in hidden controls:

```text
destination_suburb = ADELAIDE
state              = SA
postcode           = 5000
```

The API payload therefore remains unchanged. Editing the visible destination
text after a selection clears all three hidden values and requires the user to
select a valid autocomplete option again. This prevents a suburb from being
combined with stale state or postcode data.

## Existing behaviour preserved

The following identifiers remain unique and available to the current inline
JavaScript:

```text
active_client
from_address_id
suburb_search
suburb_results
destination_suburb
state
postcode
tailgate
preselect_sku
cubic_margin_percent
lines
total_weight
total_cubic
calc_status
error
results
```

The following functions and endpoint retain their current responsibilities:

```text
changeActiveClient()
showSuburbOptions()
pickSuburbObj()
addLine()
productSearch()
pickProduct()
updateProductTotals()
validateCubicMargin()
calculate()
/api/calculate/
```

`item_count` displays the number of visible shipment rows. It is not sent to
Django and does not affect consolidation or rating.

`state` and `postcode` remain unique DOM identifiers for browser-side payload
construction but are no longer displayed as separate fields.

## Responsive behaviour

- Desktop: summary remains in the right column and can stay visible while
  scrolling.
- Tablet: the layout uses the available width while retaining horizontal table
  scrolling when needed.
- Mobile: Route, Shipment, Shipment summary and Results stack vertically.
- Product and suburb autocomplete dropdowns remain anchored to their fields.

## Explicit exclusions

The refresh does not implement:

- saved shipments;
- quotation persistence or history;
- carrier-result detail navigation;
- a multi-step wizard;
- new calculation options;
- any database or model change.

## Change boundary

Production behaviour changes are limited to:

```text
app/templates/freight/calculator.html
app/static/css/app.css
```

Tests and documentation change separately. Python calculation, view, model,
import and API code remain untouched. No migration is required.

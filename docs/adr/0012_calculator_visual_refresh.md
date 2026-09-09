# ADR 0012 — Calculator presentation-only refresh

- **Status:** Accepted and implemented in source.
- **Date:** 2026-07-31.

## Context

The existing calculator is operational but its controls, totals, primary action
and carrier results are distributed across similarly weighted cards. The
approved reference provides clearer visual hierarchy through Route, Shipment,
a right-hand summary and card-style freight options.

The current release does not have a saved-shipment model, quotation workflow,
carrier-detail page or multi-step wizard.

## Decision

Implement the approved visual hierarchy without the
`Destination / Shipment / Compare rates` progress strip.

Preserve the existing DOM IDs, JavaScript functions, `/api/calculate/` request
payload and backend services. Move the existing totals and Calculate button
visually rather than creating alternative calculation paths.

Add only one presentation value: `item_count`, derived from visible table rows
and excluded from the request.

## Consequences

- No model, migration, database or calculation change.
- No Excel-vs-Django expected value changes.
- Login, authorisation and server-side client selection remain unchanged.
- Calculator CSS is scoped under `.calculator-page` so the login design is not
  restyled.
- Saved shipment and result-detail controls remain absent until separately
  specified and implemented.

## Verification

```powershell
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py test `
  apps.freight `
  apps.authentication_gateway.tests.test_login_flow `
  --noinput `
  -v 2
```

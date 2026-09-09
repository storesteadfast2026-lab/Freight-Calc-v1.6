# ADR 0011 — Hide unused ProductKitComponent from Django Admin

- **Status:** Accepted and implemented.
- **Date:** 2026-07-30.

## Context

`products.ProductKitComponent` stores a client, parent SKU, component SKU and
quantity as an initial equivalent for the workbook `SKU-Kits` concept.

Repository search confirms that current calculation services, imports, views
and request flows do not reference this model. Showing it in the operational
Admin therefore suggests functionality that is not currently implemented or
validated against Excel.

## Decision

Remove `ProductKitComponent` from Django Admin registration while retaining:

- the Django model;
- its database table and any existing rows;
- its original migration;
- permissions and possible future internal use.

`Product` remains registered and visible.

## Consequences

- `Product kit components` disappears from the Admin menu.
- Its former Admin URL is no longer registered.
- No migration or data deletion occurs.
- Freight calculation, product import and Excel validation are unchanged.
- Registration can be restored after kit behaviour is specified and proven
  against the workbook.

## Verification

```powershell
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations products --check --dry-run
docker compose exec web python manage.py test apps.products.tests.test_admin_visibility -v 2
```

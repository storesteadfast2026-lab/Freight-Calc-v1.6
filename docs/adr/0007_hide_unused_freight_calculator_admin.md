# ADR 0007 — Hide the unused FreightCalculator model from Django Admin

- **Status:** Accepted and implemented.
- **Date:** 2026-07-27.

## Context

`clients.FreightCalculator` stores a client, display name, version, calculation engine key and active flag. The current calculation flow does not use this Django Admin record to select formulas, rates, zones or the active calculation engine.

Displaying the model in the operational administrator suggests that changing these fields changes calculator behaviour. That is misleading and creates an unnecessary configuration risk.

## Decision

Remove `FreightCalculator` from Django Admin registration while retaining:

- the Django model;
- its database table and existing records;
- migrations;
- internal imports and future technical use.

`Client` remains registered and visible in Django Admin.

## Consequences

- `Freight calculators` disappears from the Admin menu for every user,
  including the native Super User.
- The previous Admin URL is no longer registered.
- No database migration is required.
- No calculation rule or imported data is changed.
- The model can be registered again later if it becomes operationally meaningful.

## Verification

Run:

```powershell
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations clients --check --dry-run
docker compose exec web python manage.py test apps.clients.tests.test_admin_visibility -v 2
```

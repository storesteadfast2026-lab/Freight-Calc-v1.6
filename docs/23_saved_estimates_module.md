# Saved Estimates Module

**Status:** Implemented in source  
**Module:** `apps.saved_estimates`  
**Feature flag:** `SAVED_ESTIMATES_ENABLED`

## Purpose

The module persists verified snapshots of completed freight calculations without changing the freight engine. It provides:

- manual `Save estimate` after a successful calculation;
- a saved-estimate history page;
- print-friendly HTML that can be printed or saved as PDF by the browser;
- CSV and Excel export for Internal Users;
- duplication of a saved input into a new calculation;
- client- and role-scoped object access.

The records are freight estimates, not binding quotations.

## Protected calculation boundary

The following file remains the calculation source:

```text
app/apps/freight/services/calculator.py
```

Its SHA-256 value in the source package and this implementation is:

```text
44bc2f87977968758e3c46f181970d46b78a09ee1ca9f80295993284a2246310
```

The Saved Estimates module imports and executes `FreightCalculatorService`. The freight engine does not import Saved Estimates.

When the user presses `Save estimate`:

1. the browser submits the original calculation payload and displayed results;
2. the server resolves the authorised client again;
3. the isolated calculation bridge builds the existing `FreightRequest` DTO;
4. `FreightCalculatorService.calculate()` runs again;
5. the save is rejected if the verified server result differs from the displayed result;
6. matching input and output snapshots are stored.

This prevents browser-edited amounts from being stored and avoids changing the existing `/api/calculate/` request or response contract.

## Integration points

Existing source changes are deliberately limited:

| Existing file | Integration |
|---|---|
| `config/settings/base.py` | Registers the app and feature flag. |
| `config/urls.py` | Mounts page and API routes. |
| `apps/freight/views.py` | Supplies UI feature/role flags only. |
| `templates/freight/calculator.html` | Includes isolated button partials, stylesheet and script; emits calculation lifecycle events. |
| `.env.example` | Documents the feature flag. |

No freight formula, resolver, validator, consolidator, rate, zone, Fuel or Tailgate service is changed.

## Data model

`SavedEstimate` contains:

- reference in `EST-YYYYMMDD-NNNNNN` format;
- Client and creating User references;
- creator label retained if the User is later removed;
- `schema_version`;
- versioned `input_snapshot` and `result_snapshot` JSON documents;
- indexed summary fields for destination, totals and best estimate;
- optional future selected-option index;
- created and updated timestamps.

The migration is additive and creates only the `saved_estimates_savedestimate` table and its indexes.

## Access rules

| User | History | Print/PDF | CSV/Excel | Duplicate |
|---|---|---|---|---|
| Customer User | Own estimates for assigned Client | Yes | No | No |
| Internal User | Estimates for authorised Clients | Yes | Yes | Yes |
| Administrator / Super User | Estimates within effective access | Yes | Yes | Yes |

Every object lookup starts from the user's permitted queryset. A reference alone does not grant access.

## Feature isolation

Disable the module without changing calculator operation:

```text
SAVED_ESTIMATES_ENABLED=0
```

When disabled:

- calculator buttons and history link are absent;
- Saved Estimates pages and APIs return 404;
- the existing calculation page and `/api/calculate/` continue to operate;
- existing saved records remain in PostgreSQL.

## Installation

The Docker start command already runs Django migrations. After rebuilding the web image, migration `saved_estimates.0001_initial` creates the new table.

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose exec -T web python manage.py showmigrations saved_estimates
docker compose exec -T web python manage.py check
```

Expected migration state:

```text
saved_estimates
 [X] 0001_initial
```

Do not use `docker compose down -v`; that removes the PostgreSQL volume.

## Test evidence

The dedicated tests cover:

- verified recalculation before persistence;
- rejection of mismatched browser results;
- Customer User ownership restrictions;
- Internal User authorised-client visibility;
- Customer export denial;
- CSV and Excel export;
- duplication payload;
- feature-flag isolation;
- preservation of the existing calculation endpoint and UI contract.

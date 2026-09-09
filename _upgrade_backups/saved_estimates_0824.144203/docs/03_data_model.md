# Data Model

## Current operational entities

- `Client`
- `FreightCalculator`
- `FromAddress`
- `Suburb`
- `Product`
- `Carrier`
- `CarrierService`
- `ClientCarrierConfig`
- `FreightZone`
- `FreightRate`
- `CarrierTailgateCharge`
- `ExternalDataFile`
- `ProductSourceRow`
- `StockSourceRow`
- `AuditEvent`

The design keeps client-specific products, rates, zones, configurations and external files separated by `client_id` where required.

## Operational data vs reference staging

`Product` is the operational product master used by the calculator.

`ProductSourceRow` and `StockSourceRow` are isolated, read-only staging/reference tables associated with an `ExternalDataFile`:

- validating `product_sth.xlsx` replaces only the rows for that uploaded Product source file;
- validating `stock_sth.xlsx` replaces only the rows for that uploaded Stock source file;
- neither process changes `Product`, `FreightRate`, `FreightZone`, `ClientCarrierConfig` or calculation logic;
- each source row retains raw source data and validation information.

## External-file provenance

`ExternalDataFile` stores:

- client and file type;
- physical file path;
- source method/URL;
- original filename, MIME type and size;
- SHA-256 content hash;
- status and validation summary;
- upload/validation/import/activation/rollback actors and timestamps;
- previous active file and import summaries;
- error information.

## Fuel provenance

`ClientCarrierConfig` stores operational fuel provenance through:

- `fuel_levy_source`;
- `fuel_levy_updated_at`;
- `fuel_data_file`.

## Audit

`AuditEvent` includes actor, client, external file, event type, severity, message, metadata, IP address, request ID and timestamp. The Django Admin view is intended to be read-only; application services create events.

## Current user model

The project uses Django's built-in `auth.User` and an implemented one-to-one `CalculatorUserProfile`. No custom `AUTH_USER_MODEL` is introduced.

`CalculatorUserProfile` stores:

- `CUSTOMER_USER` or `INTERNAL_USER` role;
- single/all/selected client scope;
- one customer client when applicable;
- selected internal clients when applicable;
- calculator-access entitlement.

`User.is_active` remains the account-status source of truth.

## User access Version 1 — 2026-07-22

`authentication_gateway.CalculatorUserProfile` extends the existing Django user without replacing `AUTH_USER_MODEL`.

```text
auth.User 1 ─── 1 CalculatorUserProfile
CalculatorUserProfile N ─── 1 Client             (Customer User only)
CalculatorUserProfile N ─── N Client             (selected Internal clients)
```

Valid combinations:

| Role | Scope | `client` | `allowed_clients` |
|---|---|---|---|
| Customer User | Single client | Required | Empty |
| Internal User | All clients | Empty | Empty |
| Internal User | Selected clients | Empty | One or more active clients |

The database check constraint covers role, scope and single-client consistency. M2M and staff restrictions are validated by the Admin form and creation command.

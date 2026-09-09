# Data Model

Main entities:

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
- `AuditEvent`

The design keeps client-specific products, rates, zones and configurations separated by `client_id`.

## Fuel import provenance

`ExternalDataFile` stores the physical file, source method/URL, SHA-256, validation result, activation history, rollback relationship and import summaries.

`ClientCarrierConfig` stores operational fuel provenance through:

- `fuel_levy_source`
- `fuel_levy_updated_at`
- `fuel_data_file`

`AuditEvent` now includes `client`, `external_file`, `severity`, `ip_address` and `request_id`. The Django Admin view is read-only; application services create events.

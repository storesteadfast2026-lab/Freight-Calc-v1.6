# Django Admin Configuration Dictionary

**Version:** 0819.0810

This document explains what each administration section represents, where its data originates and its current effect.

| admin_section | model | purpose | key_fields | excel_source | current_effect | caution | trace_ids |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Clients > Clients | Client | Defines the logical owner of data and configuration. | code, name, active | No direct equivalent; the workbook represents STH. | `resolve_client` requires `active=True`. | Deactivating STH prevents calculation. | SYS-CLIENT-001 |
| Hidden from Admin: FreightCalculator | FreightCalculator | Records the internal name, version and engine key. | client, name, version, calculation_engine_key, active | Version V2026.R2. | No active engine selection and no Admin screen. | Do not assume that `active` or the engine key changes the current calculation. | SYS-CALC-001 |
| Locations > From addresses | FromAddress | Web origin address for each client. | client, name, suburb, state, postcode, is_default, active | Web-only requirement. | Displayed in the selector; does not affect calculation. | `is_default` does not automatically select an option in the current template. | UI-FROM-001 |
| Locations > Suburbs | Suburb | Global suburb/state/postcode master. | suburb_name, state, postcode, normalized_key | SUBURBS. | Autocomplete and postcode resolution. | Do not delete matches used by fixtures. | LOC-SUBURB-001, LOC-STATE-001, LOC-POST-001 |
| Products > Products | Product | Client-specific SKU master. | sku, dimensions, weight_kg, cubic_m3, freight_type, active | SKUs. | Populates form lines. | Manual changes are overwritten by `--replace`; confirm `cubic * quantity`. | PROD-SKU-001, PROD-DIM-001, PROD-WGT-001, PROD-CUB-001, PROD-TYPE-001 |
| Hidden from Admin: ProductKitComponent | ProductKitComponent | Initial compatibility model for kit relationships. | parent_sku, component_sku, quantity | Initial concept associated with SKU-Kits; behaviour is unconfirmed. | No confirmed use in calculation, imports, views or services. | Do not delete the table or data until kit logic is specified and validated against Excel. | PROD-007 |
| Carriers > Carriers | Carrier | Primary transport provider. | code, name, active | FuelSurcharge/ZONES/RATES/SettingFlags. | Visible code and grouping. | `active` is not queried directly by the engine. | CFG-CARRIER-001 |
| Carriers > Carrier services | CarrierService | Service belonging to a carrier. | carrier, service_code, service_name, active | Service in FuelSurcharge/ZONES/RATES. | Forms `excel_key` and links configuration, zone and rate. | Do not change codes without reimporting relationships; `active` is not queried directly. | CFG-SERVICE-001 |
| Carriers > Client carrier configs | ClientCarrierConfig | Configures how a service operates for a client. | base_status, active, ratecard, fuel, fuel provenance, uprate, cubic conversion, P/C/tailgate/zone/handling flags | Primarily FuelSurcharge G:AD; operational fuel from ExternalDataFile; handling amount from SettingFlags!E20. | Determines eligibility, zone, volumetric weight and surcharges. | Fuel levy source/updated/file are read-only; the active Admin dataset is reapplied after normal imports. | CFG-CUSTOMER-001 to CFG-PCZONE-001, FUEL-PROV-001 |
| Rates > Freight zones | FreightZone | Maps a destination to zone/subzone/area for a carrier service. | suburb, state, postcode, zone, subzone, area | ZONES. | No result when `zone_enabled=True` and no zone is found. | Suburb+state takes priority; TEAMEX does not use unrestricted postcode fallback. | ZONE-MAP-001 |
| Rates > Freight rates | FreightRate | Rate rows and charges. | zone/subzone/area, weight_break, freight_type, customer_code, minimum/basic/subsequent/per_kg | RATES. | Calculates `freight_base` and several extras. | `margin` and `overlength_charge` are currently unused; retain six-decimal precision. | RATE-KEY-001 to RATE-MARGIN-001 |
| Rates > Carrier tailgate charges | CarrierTailgateCharge | Tailgate and hand-unload amounts by client/carrier. | minimum_charge, per_subsequent_charge, hand_unload_charge | SettingFlags rows 34:52. | Calculates the pallet-based charge. | Configuration is per carrier, not per service. | TAIL-MIN-001, TAIL-PER-001, HAND-AMT-001 |
| Audit > Audit events | AuditEvent | Immutable audit record for system operations. | actor, client, external_file, event_type, severity, message, metadata, ip_address, request_id, created_at | None. | Fuel services create automatic fetch/upload/validation/activation/failure/rollback events. | The screen is read-only and does not permit creating or deleting events through Admin. | AUDIT-001, FUEL-SRC-001, FUEL-ROLL-001 |
| Imports > External data files | ExternalDataFile | Register and stored file for external sources by client. | file_type, source_method, uploaded_file, sha256, status, validation_summary, actors/timestamps | product_sth.xlsx, stock_sth.xlsx, fuel.csv | Centralises upload, validation and audit; Fuel also supports activation/rollback. | Product/Stock are reference data; Fuel can change `fuel_levy`. Do not delete history. | IMP-EXT-001 |
| Imports > Product source rows | ProductSourceRow | Validated `product_sth.xlsx` rows for reference and comparison. | product_code, dimensions, cubic, quantity, weight, pallet, status, raw_data | product_sth.xlsx | Does not participate in autocomplete or calculation and does not modify Product. | Read-only view; duplicate SKUs within the source fail validation. | IMP-PROD-001 |
| Imports > Stock source rows | StockSourceRow | Validated `stock_sth.xlsx` rows for reference. | movement, product_code, quantity, pallet, weight, cubic, location, status, raw_data | stock_sth.xlsx | Does not participate in calculation and does not modify Product. | Read-only view; repeated SKUs are retained because they may represent multiple movements. | IMP-STOCK-001 |

## Modification rule

Before changing a record imported from Excel:

1. Identify its `trace_ids`.
2. Review the source worksheet/cell.
3. Create or select an Excel-vs-Django case.
4. Change only the minimum code or data required.
5. Run the battery with the corresponding baseline.
6. Update the matrix, `docs/02_calculation_flow.md`, `docs/11_validation_runbook.md` and `docs/12_validation_findings_log.md` where applicable.

## Fuel import controls added 2026-07-17

| Admin location | Control | Effect |
|---|---|---|
| Imports -> External data files | Fetch fuel from source | Exposes an editable HTTP/HTTPS URL, remembers the last successfully validated URL per client, downloads and validates; does not activate rates |
| Imports -> External data files | Add external data file | Uploads a local `fuel.csv` snapshot |
| External data file row | Validate | Builds ratecard preview and safety checks |
| External data file row | Activate | Updates matching `ClientCarrierConfig.fuel_levy` values transactionally |
| Active external data file | Rollback | Restores values recorded before activation |
| Carriers -> Client carrier configs | Fuel levy source / updated at / data file | Read-only provenance of the operational value |
| Audit -> Audit events | Read-only event history | Records actor, client, file, event, severity, IP, request ID and metadata |

## Product and Stock controls added 2026-07-20

| Admin location | Control | Effect |
|---|---|---|
| Imports -> External data files | Upload product source | Uploads and immediately validates `product_sth.xlsx` into ProductSourceRow |
| Imports -> External data files | Upload stock source | Uploads and immediately validates `stock_sth.xlsx` into StockSourceRow |
| Product/Stock external file | Validate | Rebuilds isolated source rows for that file; no operational data change |
| Product/Stock external file | View rows | Opens the read-only staging rows filtered by source file |
| Product/Stock external file | Download | Downloads the stored source snapshot |

Product and Stock retain client/type/file history, including the original filename. Their local filesystem directory is not available to Django and cannot be prefilled by the browser. Remote Product/Stock fetch remains a future feature and is not introduced by the remembered Fuel URL change.

Product/Stock rows must never show `Activate` or `Rollback`.

Important: `import_sth_excel --replace` is a separate full-workbook operation. In the selected database it deletes non-Fuel `ExternalDataFile` records and, by cascade, Product/Stock source rows. Run Excel validation batteries in an isolated database as documented in `docs/11_validation_runbook.md`.

## Minimum user and Django Admin implementation

| Concept | Version 1 behaviour |
|---|---|
| Customer User | Calculator role; exactly one active client; never staff |
| Internal User | Calculator role; all or selected active clients |
| Administrator | `Administrators` group; Internal User with ALL_CLIENTS and automatic `is_staff` |
| Super User | Native Django superuser account `super`; primary group and calculator profile optional |

Sensitive Fuel and source operations use explicit permissions inherited from `Administrators`. Group records, Permission records and superuser status remain controlled by the Super User to avoid privilege escalation.

## User and permission configuration - 2026-07-22

### Calculator User Profiles

The standalone profile view remains visible only to the Super User. Normal Users are configured through the group-based User form.

### Administrators group

Created idempotently with:

```powershell
docker compose exec web python manage.py setup_access_roles
```

It grants view/add/change for current operational configuration models, view-only access to audit/source rows and custom import-action permissions. It does not grant auth User, Group or Permission management.

### ExternalDataFile custom permissions

| Permission | Operation |
|---|---|
| `validate_external_data_file` | Validate Product, Stock or Fuel source |
| `activate_fuel` | Apply validated Fuel rates |
| `rollback_fuel` | Restore values before an activation |
| `download_external_data_file` | Download stored source file |

### Super User

Created with Django `createsuperuser --username super`. Use for user/group administration, recovery and exceptional operations.

<!-- USER_ADMIN_INTEGRATION_0727.0802 -->
## Authentication and Authorization > Users

The list displays calculator status, role, client scope, client access and Django Admin level. The User form includes an optional Calculator access block. The standalone profile model is hidden from the menu.

## Group-only User form - 2026-07-30

The User add/change form now exposes `Primary access group` and, only when needed, `Customer client`. It does not expose individual `User permissions`, manual Staff status or manual Superuser status.

| Primary group | Calculator mapping | Django Admin |
|---|---|---|
| Administrators | Internal User / All clients | Operational access |
| Customers | Customer User / Single client | None |
| Steadfast Users | Internal User / All clients | None |

The effective-access summary is read-only and shows the source group, calculator scope and Django Admin level.

## FreightCalculator Admin visibility decision - 2026-07-27

`clients.FreightCalculator` is intentionally not registered in Django Admin because its current fields do not control the active calculation flow. The model remains available internally for compatibility and possible future engine/version management.

Operational administrators should use:

```text
Clients > Clients
```

There is no supported operational Admin screen for `FreightCalculator` in the current release.

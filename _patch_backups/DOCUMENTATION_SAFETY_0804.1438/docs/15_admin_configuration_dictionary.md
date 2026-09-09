# Diccionario de configuración de Django Admin

**Versión:** 0722.1350

Este documento explica qué representa cada sección de administración, de dónde proviene y qué efecto tiene actualmente.

| seccion_admin | modelo | proposito | campos_clave | origen_excel | efecto_actual | precaucion | trace_ids |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Clients > Clients | Client | Define el propietario lógico de datos y configuraciones. | code, name, active | No directo; el workbook corresponde a STH. | resolve_client exige active=True. | Desactivar STH impide calcular. | SYS-CLIENT-001 |
| Clients > Freight calculators | FreightCalculator | Registra nombre, versión y engine key. | client, name, version, calculation_engine_key, active | Versión V2026.R2. | Sin selección activa del motor. | No asumir que active/engine key cambian el cálculo actual. | SYS-CALC-001 |
| Locations > From addresses | FromAddress | Dirección origen web por cliente. | client, name, suburb, state, postcode, is_default, active | Requisito web. | Se muestra en selector; no afecta cálculo. | is_default no selecciona automáticamente en la plantilla actual. | UI-FROM-001 |
| Locations > Suburbs | Suburb | Maestro global de suburb/state/postcode. | suburb_name, state, postcode, normalized_key | SUBURBS. | Autocompletado y resolución de postcode. | No borrar coincidencias usadas por fixtures. | LOC-SUBURB-001, LOC-STATE-001, LOC-POST-001 |
| Products > Products | Product | Maestro SKU por cliente. | sku, dimensions, weight_kg, cubic_m3, freight_type, active | SKUs. | Rellena líneas del formulario. | Cambios manuales se sobrescriben con --replace; confirmar cubic*quantity. | PROD-SKU-001, PROD-DIM-001, PROD-WGT-001, PROD-CUB-001, PROD-TYPE-001 |
| Products > Product kit components | ProductKitComponent | Modelo inicial de compatibilidad para relaciones de kits. | parent_sku, component_sku, quantity | Concepto inicial asociado a SKU-Kits; comportamiento no confirmado. | Sin uso confirmado en cálculo, importaciones, vistas o servicios; oculto del Admin. | No borrar tabla ni datos hasta especificar y validar la lógica de kits contra Excel. | PROD-007 |
| Carriers > Carriers | Carrier | Transportista principal. | code, name, active | FuelSurcharge/ZONES/RATES/SettingFlags. | Código visible y agrupación. | active no se consulta directamente por el motor. | CFG-CARRIER-001 |
| Carriers > Carrier services | CarrierService | Servicio perteneciente a un carrier. | carrier, service_code, service_name, active | Service en FuelSurcharge/ZONES/RATES. | Forma excel_key y enlaza config/zona/tarifa. | No cambiar códigos sin reimportar relaciones; active no se consulta directamente. | CFG-SERVICE-001 |
| Carriers > Client carrier configs | ClientCarrierConfig | Configura cómo un servicio opera para un cliente. | base_status, active, ratecard, fuel, fuel provenance, uprate, cubic conversion, flags P/C/tailgate/zone/handling | Principalmente FuelSurcharge G:AD; fuel operativo desde ExternalDataFile; handling amount en SettingFlags!E20. | Decide elegibilidad, zona, peso volumétrico y recargos. | Fuel levy source/updated/file son de solo lectura; el dataset Admin activo se reaplica tras imports normales. | CFG-CUSTOMER-001 a CFG-PCZONE-001, FUEL-PROV-001 |
| Rates > Freight zones | FreightZone | Mapea destino a zone/subzone/area por carrier service. | suburb, state, postcode, zone, subzone, area | ZONES. | Sin zona no hay resultado cuando zone_enabled=True. | Suburb+state tiene prioridad; TEAMEX no usa fallback libre por postcode. | ZONE-MAP-001 |
| Rates > Freight rates | FreightRate | Filas tarifarias y cargos. | zone/subzone/area, weight_break, freight_type, customer_code, minimum/basic/subsequent/per_kg | RATES. | Calcula freight_base y varios extras. | margin y overlength_charge no se usan actualmente; conservar precisión de 6 decimales. | RATE-KEY-001 a RATE-MARGIN-001 |
| Rates > Carrier tailgate charges | CarrierTailgateCharge | Importes de tailgate y hand unload por cliente/carrier. | minimum_charge, per_subsequent_charge, hand_unload_charge | SettingFlags filas 34:52. | Calcula cargo con pallets. | La configuración es por carrier, no por service. | TAIL-MIN-001, TAIL-PER-001, HAND-AMT-001 |
| Audit > Audit events | AuditEvent | Registro de auditoría inmutable para operaciones del sistema. | actor, client, external_file, event_type, severity, message, metadata, ip_address, request_id, created_at | Ninguno. | Los servicios de fuel crean eventos automáticos de fetch/upload/validación/activación/fallo/rollback. | La pantalla es de solo lectura y no permite crear ni borrar eventos desde Admin. | AUDIT-001, FUEL-SRC-001, FUEL-ROLL-001 |
| Imports > External data files | ExternalDataFile | Registro y archivo de fuentes externas por cliente. | file_type, source_method, uploaded_file, sha256, status, validation_summary, actors/timestamps | product_sth.xlsx, stock_sth.xlsx, fuel.csv | Centraliza carga, validación, auditoría y, solo para Fuel, activación/rollback. | Product/Stock son referencia; Fuel puede cambiar fuel_levy. No borrar historial. | IMP-EXT-001 |
| Imports > Product source rows | ProductSourceRow | Filas validadas de product_sth.xlsx para referencia y comparación. | product_code, dimensiones, cubic, quantity, weight, pallet, status, raw_data | product_sth.xlsx | No participa en autocomplete ni cálculo; no modifica Product. | Vista de solo lectura; duplicados internos de SKU fallan validación. | IMP-PROD-001 |
| Imports > Stock source rows | StockSourceRow | Filas validadas de stock_sth.xlsx para referencia. | movement, product_code, quantity, pallet, weight, cubic, location, status, raw_data | stock_sth.xlsx | No participa en cálculo ni modifica Product. | Vista de solo lectura; SKU repetido se conserva porque puede representar movimientos múltiples. | IMP-STOCK-001 |

## Regla de modificación

Antes de cambiar un registro importado desde Excel:

1. Identifica sus `trace_ids`.
2. Revisa la hoja/celda de origen.
3. Crea o selecciona un caso Excel vs Django.
4. Cambia el código o el dato mínimo necesario.
5. Ejecuta la batería con el baseline correspondiente.
6. Actualiza la matriz, `docs/02_calculation_flow.md`, `docs/11_validation_runbook.md` y `docs/12_validation_findings_log.md` cuando corresponda.

## Fuel import controls added 2026-07-17

| Admin location | Control | Effect |
|---|---|---|
| Imports → External data files | Fetch fuel from source | Exposes an editable HTTP/HTTPS URL, remembers the last successfully validated URL per client, downloads and validates; does not activate rates |
| Imports → External data files | Add external data file | Uploads a local `fuel.csv` snapshot |
| External data file row | Validate | Builds ratecard preview and safety checks |
| External data file row | Activate | Updates matching `ClientCarrierConfig.fuel_levy` values transactionally |
| Active external data file | Rollback | Restores values recorded before activation |
| Carriers → Client carrier configs | Fuel levy source / updated at / data file | Read-only provenance of the operational value |
| Audit → Audit events | Read-only event history | Records actor, client, file, event, severity, IP, request ID and metadata |

## Product and Stock controls added 2026-07-20

| Admin location | Control | Effect |
|---|---|---|
| Imports → External data files | Upload product source | Uploads and immediately validates `product_sth.xlsx` into ProductSourceRow |
| Imports → External data files | Upload stock source | Uploads and immediately validates `stock_sth.xlsx` into StockSourceRow |
| Product/Stock external file | Validate | Rebuilds isolated source rows for that file; no operational data change |

Product and Stock retain client/type/file history, including the original
filename. Their local filesystem directory is not available to Django and
cannot be prefilled by the browser. Remote Product/Stock fetch remains a future
feature and is not introduced by the remembered Fuel URL change.
| Product/Stock external file | View rows | Opens the read-only staging rows filtered by source file |
| Product/Stock external file | Download | Downloads the stored source snapshot |

Product/Stock rows must never show `Activate` or `Rollback`.

## Minimum user and Django Admin implementation

| Concept | Version 1 behavior |
|---|---|
| Customer User | Calculator role; exactly one active client; never staff |
| Internal User | Calculator role; all or selected active clients |
| Administrator | `Administrators` group; Internal User with ALL_CLIENTS and automatic `is_staff` |
| Super User | Native Django superuser account `super`; primary group and calculator profile optional |

Sensitive Fuel and source operations use explicit permissions inherited from `Administrators`. Group records, Permission records and superuser status remain controlled by the Super User to avoid privilege escalation.

## User and permission configuration — 2026-07-22

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

## Group-only User form — 2026-07-30

The User add/change form now exposes `Primary access group` and, only when
needed, `Customer client`. It does not expose individual `User permissions`,
manual Staff status or manual Superuser status.

| Primary group | Calculator mapping | Django Admin |
|---|---|---|
| Administrators | Internal User / All clients | Operational access |
| Customers | Customer User / Single client | None |
| Steadfast Users | Internal User / All clients | None |

The effective-access summary is read-only and shows the source group, calculator
scope and Django Admin level.


## FreightCalculator Admin visibility decision — 2026-07-27

`clients.FreightCalculator` is intentionally not registered in Django Admin because its current fields do not control the active calculation flow. The model remains available internally for compatibility and possible future engine/version management.

Operational administrators should use:

```text
Clients > Clients
```

There is no supported operational Admin screen for `FreightCalculator` in the current release.


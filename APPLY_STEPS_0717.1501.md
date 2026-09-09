# Aplicación del cambio: Fuel on demand desde Django Admin

**Versión:** 0717.1501

## Qué incorpora

- Descarga manual desde `https://www.poscat.com.au/fuelsc/fuel.csv`.
- Upload alternativo de una copia local `fuel.csv`.
- Validación, vista previa, activación transaccional y rollback.
- Historial de archivos con SHA-256.
- Auditoría automática y de solo lectura.
- Procedencia del fuel visible en `Client carrier configs`.
- Preservación del fuel Admin cuando se vuelve a importar el workbook.
- Separación entre fuel operativo y fuel histórico de las baterías Excel.

## Aplicar en PowerShell

Cierra cualquier editor que esté bloqueando archivos y entra al proyecto:

```powershell
cd C:\docker-projects\Freight-Calc-05jun
```

Crea un respaldo del código actual:

```powershell
$stamp = Get-Date -Format "MMdd.HHmm"
Compress-Archive -Path .\* -DestinationPath "..\Freight-Calc-before-fuel-$stamp.zip" -Force
```

Expande este paquete directamente en la raíz del proyecto:

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\STH_Fuel_Admin_OnDemand_0717.1501.zip" -DestinationPath "C:\docker-projects\Freight-Calc-05jun" -Force
```

No ejecutes `docker compose down -v`, porque eliminaría la base PostgreSQL.

## Variables de entorno

No reemplaces tu `.env`. Agrega estas líneas si no existen:

```text
FUEL_SOURCE_URL=https://www.poscat.com.au/fuelsc/fuel.csv
FUEL_FETCH_TIMEOUT_SECONDS=30
FUEL_RATE_MAX=1.0
MEDIA_ROOT=/app/uploaded_data
```

## Reconstruir y migrar

```powershell
docker compose up -d --build
```

El comando de inicio ya ejecuta:

```text
python manage.py migrate --noinput
```

Verifica las migraciones:

```powershell
docker compose exec web python manage.py showmigrations imports audit carriers
```

Deben aparecer marcadas:

```text
imports.0002_fuel_admin_import
audit.0002_fuel_audit_fields
carriers.0003_fuel_provenance
```

## Probar

```powershell
docker compose exec web python manage.py test apps.freight.tests.test_consolidator apps.freight.tests.test_tailgate apps.imports.tests.test_fuel_import -v 2
```

## Uso en Django Admin

```text
Imports
→ External data files
→ Fetch fuel from source
```

1. Selecciona `STH`.
2. Presiona `Fetch and validate`.
3. Abre el registro descargado.
4. Revisa `Validation summary` y `Preview`.
5. Presiona `Activate`.
6. Revisa `Carriers → Client carrier configs`.
7. Confirma `Fuel levy source = ADMIN_WEB_FETCH`.
8. Revisa `Audit → Audit events`.

El fuel no cambia durante la descarga o validación. Solo cambia al presionar `Activate`.

## Recuperación

Para reaplicar el último dataset activo:

```powershell
docker compose exec web python manage.py reapply_active_fuel --client STH
```

## Rollback

En el registro `ACTIVE`, presiona `Rollback` e ingresa un motivo. El sistema restaura los valores anteriores almacenados durante la activación.

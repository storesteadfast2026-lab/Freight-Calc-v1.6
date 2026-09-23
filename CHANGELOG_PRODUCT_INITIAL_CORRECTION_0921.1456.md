# Product Initial Correction 0921.1456

## Resultado

- Corrige el importador inicial: las columnas `Length (cm)` y `Width (cm)` ya
  no se guardan como `Product.name` y `Product.description`.
- Añade `Prepare recommended initial correction` para crear borradores masivos:
  texto desde Source, valores físicos operativos protegidos y C/P derivado de
  `pallet = 0 → C`, `pallet > 0 → P`.
- Añade Preview y Apply transaccional con usuario, fecha, lote y auditoría.
- Añade rollback del último lote aplicado.
- Permite retirar productos operational-only únicamente después de comprobar
  referencias en kits y cotizaciones guardadas.
- Mantiene los SKU source-only como referencia por defecto.
- Detecta posibles diferencias de escala ×10/÷10 en dimensiones, conserva el
  valor crudo en milímetros y bloquea su uso hasta revisión manual.
- Hace transversal el grupo `C/P differs from pallet rule`.

## Datos esperados para la carga analizada

- 229 productos coincidentes: corrección recomendada de Name/Description.
- 3 operational-only: retiro controlado si continúan sin referencias.
- Las diferencias físicas no se reemplazan en la corrección recomendada.

## Verificación

- 141 pruebas del módulo Imports superadas.
- Migración `imports.0013_product_reconciliation_apply` validada.

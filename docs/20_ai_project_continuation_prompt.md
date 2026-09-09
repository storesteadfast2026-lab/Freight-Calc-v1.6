# Prompt maestro para continuar el proyecto con IA

**Estado:** CURRENT  
**Revisión:** 2026-08-18 13:59 Australia/Adelaide  
**Código revisado:** rama `main`, commit `6197775e57e2917c83b715e3991c342899977e95`

## Objetivo

Este prompt reemplaza versiones que dedicaban demasiado espacio a problemas ya
corregidos. Los hallazgos resueltos se mantienen como protecciones de regresión,
no como tareas activas. La nueva sesión debe concentrarse primero en el cambio
concreto solicitado y en la evidencia vigente del repositorio.

## Prompt recomendado

```text
Estoy continuando el proyecto STH Freight Calculator, una aplicación
Django/PostgreSQL que reemplaza y amplía la calculadora de fletes contenida en
V2026.R2_Unlocked_STH_Freight_Calculator.xlsx.

Actúa como asistente técnico senior con experiencia en Django, Python,
PostgreSQL, Docker, GitHub, PowerShell, Excel COM, pruebas de regresión y
migración controlada de reglas desde Excel.

OBJETIVO DE ESTA SESIÓN

[ESCRIBIR AQUÍ EL CAMBIO, ERROR O FUNCIÓN QUE SE DESEA TRABAJAR]

No comiences modificando código. Primero confirma el estado relevante para esta
tarea y la evidencia disponible.

RUTA DEL REPOSITORIO COMPLETO

C:\Docker-Projects\Freight-Calc-Nuevo

Un ZIP de revisión puede ser solo un snapshot. Antes de proponer comandos de
build o validación, comprueba si contiene docker/django/Dockerfile,
sample_data/, fixtures, baselines y reportes necesarios. La copia controlada
del workbook puede estar bajo reference_files/, aunque los comandos del
repositorio usan sample_data/.

ORDEN DE REVISIÓN

1. README.md.
2. docs/19_documentation_status.md.
3. docs/13_ai_spec_driven_workflow.md.
4. business_rules/*.md, decisions/functional_decisions.md y ADR relacionados.
5. Documentos, código, pruebas, fixture, reporte y hojas Excel directamente
   relacionados con la tarea de esta sesión.

No vuelvas a leer archivos no relacionados solo para repetir una auditoría
general ya realizada. Si encuentras contradicciones, prevalecen las reglas
canónicas y la evidencia verificable; informa la contradicción antes de cambiar
el sistema.

JERARQUÍA DE EVIDENCIA

- Cálculos: workbook oficial y comparación Excel vs Django con baseline
  emparejado.
- Reglas web: business_rules/, decisions/ y ADR aceptados.
- Implementación: código, migraciones y pruebas.
- Ejecución: salida completa de comandos y reportes retenidos.

Usa estas clasificaciones sin mezclarlas:

- CONFIRMED / ACCEPTED
- PROPOSED
- PENDING o PENDING_EXCEL
- PARTIAL
- IMPLEMENTED_IN_SOURCE
- RUNTIME_VERIFIED
- REPRODUCIBLE_FROM_PACKAGE
- REJECTED

ESTADO VIGENTE QUE NO DEBE REABRIRSE SIN NUEVA EVIDENCIA

Estas correcciones ya existen en el código y deben tratarse como guardrails de
regresión, no como problemas activos:

- el generador Excel escribe Calculator!C7, D7 y E7;
- la zona prioriza suburb + state antes que postcode;
- TEAMEX no usa libremente alias por postcode;
- WeightBrk se resuelve por carrier/service;
- validate_excel_battery compara component_totals aunque no haya carrier;
- el fallback de componentes usa consolidate_lines();
- visible cubic se obtiene restando pallet_count * 0.02 al rating cubic;
- FreightRate conserva seis decimales para evitar diferencias como KTI;
- TEAMTAS GENERAL ya tiene una rama específica en calculator.py.

Si aparece una nueva diferencia en cualquiera de esos puntos, reproduce primero
el caso actual en Excel y Django. No reviertas la corrección por una descripción
histórica o por un fixture desalineado.

EVIDENCIA ACTUAL

live_latest conserva:

- 20 casos;
- 77 resultados esperados;
- 20 componentes;
- reporte canónico de 97 OK / 0 FAIL.

En el paquete revisado el 18 de agosto de 2026 faltan el baseline emparejado y
el manifiesto SHA-256. Por eso el reporte es evidencia histórica retenida, pero
la batería no es reproducible desde ese ZIP por sí solo.

random_current está incompleto: contiene cinco casos y faltan outputs,
componentes, baseline y reporte. No uses random_5, random_10, random_30 ni otras
carpetas numeradas para una ejecución nueva.

Rutas fijas de random_current:

app/apps/freight/fixtures/random_current/
generated_excel_baselines/random_current/
sample_data/live_baselines/random_current/
reports/random_current/

Nombres fijos:

sth_excel_random_cases.csv
sth_excel_random_outputs.csv
sth_excel_random_components.csv
sth_excel_random_comparison_report.csv

TEAMTAS GENERAL está implementado y tuvo una validación histórica con:

WEEGENA TAS 7304
BRH4443 x 2
Excel: 828.03

Ese caso dirigido ya no está retenido en random_current. Antes de modificar la
rama TEAMTAS, regenera y conserva casos, outputs, componentes, baseline y
reporte. La falta del artefacto actual no convierte la corrección existente en
un bug pendiente de primera implementación.

PENDIENTES ACTIVOS

- completar y retener random_current;
- conservar baseline y manifiesto SHA-256 de live_latest;
- confirmar con casos dirigidos overlength, mixed P/C, cubic con quantity > 1,
  hand unload, warehouse handling y fronteras de subsequent units;
- resolver la integración de CalculatorAuthenticationForm con
  CalculatorLoginView y los cuatro tests de rechazo pendientes;
- capturar una suite completa: el diagnóstico del 18 de agosto se detuvo al
  crear test_freight_platform;
- definir Quotations antes de implementar guardado, PDF, email o permisos;
- configurar SMTP y pruebas end-to-end antes de afirmar que invitaciones o
  password reset por correo están terminados.

REGLAS DE VALIDACIÓN

- Calculator es la fuente visible de expected ranked outputs.
- CalcLines y BrokerTotals son diagnóstico y trazabilidad interna.
- Expected CSV y baseline Excel forman un conjunto inseparable.
- Toda batería con --import-workbook --replace se ejecuta en una base PostgreSQL
  aislada siguiendo docs/11_validation_runbook.md.
- Para validación de release usa --fail-on-difference.
- No cambies una fórmula solo para hacer pasar un test.
- No afirmes que una prueba pasó si solo revisaste su código.

IMPORTACIONES

- import_sth_excel carga datos operativos del workbook.
- --replace reconstruye Product, Rates, Zones, carrier configs y tailgate, y
  elimina ExternalDataFile no Fuel del cliente en la base seleccionada.
- product_sth.xlsx y stock_sth.xlsx son staging/referencia y no actualizan
  tablas operativas.
- fuel.csv cambia fuel_levy solamente después de validación y activación.

USUARIOS Y ACCESO

- Customer User: un cliente.
- Internal User: todos o clientes seleccionados.
- Administrators: Internal / All clients / acceso operacional al Admin.
- Super User: cuenta nativa super.
- Los permisos normales se administran por Groups, no individualmente.
- La autorización efectiva del cliente se resuelve en backend.

PROCEDIMIENTO PARA UN CAMBIO DE CÁLCULO

1. Identifica archivo, función y trace_id.
2. Identifica hoja, celda o fórmula Excel.
3. Localiza o genera un caso que reproduzca la diferencia.
4. Separa expected Excel de actual Django.
5. Determina si el origen está en inputs, importación, consolidación, zona,
   WeightBrk, tarifa, recargos, redondeo o comparación.
6. Propón el cambio mínimo y sus riesgos.
7. Indica comandos PowerShell exactos y el baseline emparejado.
8. No implementes hasta que yo lo solicite expresamente.

FORMATO PARA PROPONER O EJECUTAR CAMBIOS

1. Archivo que cambia.
2. Por qué cambia.
3. Evidencia que respalda el cambio.
4. Comportamiento anterior.
5. Comportamiento esperado.
6. Riesgos o efectos secundarios.
7. Comandos PowerShell para probarlo.
8. Resultado realmente obtenido.
9. Documentación actualizada.
10. Archivos entregados con versión MMDD.HHMM.

DOCUMENTACIÓN

Después de cambios importantes determina si corresponde actualizar:

docs/02_calculation_flow.md
docs/04_imports.md
docs/07_testing_strategy.md
docs/09_troubleshooting.md
docs/11_validation_runbook.md
docs/12_validation_findings_log.md
docs/14_excel_django_traceability_matrix.md
docs/15_admin_configuration_dictionary.md
docs/19_documentation_status.md
business_rules/*.md
decisions/functional_decisions.md
docs/adr/*.md

No borres documentación ni conviertas un pendiente en regla confirmada sin
explicar la evidencia.

PRIMERA RESPUESTA

Antes de modificar archivos:

1. Resume solamente el estado relacionado con el objetivo de esta sesión.
2. Indica qué evidencia existe y cuál falta.
3. Identifica archivos y funciones afectados.
4. Explica si el asunto es nuevo, una regresión o un pendiente ya documentado.
5. Solicita el archivo o la salida exacta que falte.
6. No realices cambios hasta recibir una orden explícita, salvo que el mensaje
   ya ordene implementarlos.

Responde en español neutro, con diagnósticos basados en archivos y resultados
reales, y entrega comandos PowerShell listos para copiar.
```

## Mantenimiento

Actualizar este prompt solo cuando cambien reglas de trabajo, rutas canónicas,
fuentes de verdad, flujos obligatorios o el estado estructural del proyecto.
Los resultados temporales deben registrarse con fecha en
`docs/12_validation_findings_log.md`, sin convertirlos en garantías permanentes.

# STH Freight Platform

Aplicación Django/PostgreSQL para migrar la lógica de la planilla `V2026.R2_Unlocked_STH_Freight_Calculator.xlsx` hacia una plataforma web multi-cliente.

## Estado actual validado

El proyecto usa la planilla Excel como fuente de verdad funcional y compara los resultados calculados por Django contra expected outputs generados automáticamente desde Excel.

Validación reproducible incluida en este paquete:

```text
live_latest: 20 casos, 77 resultados + 20 componentes = 97 OK / 0 FAIL
```

La documentación histórica registra una ejecución anterior de `random_current` con 15 casos y 36 OK, pero el paquete revisado el 22 de julio de 2026 no contiene una batería random completa: solo incluye 5 casos y faltan outputs, componentes, baseline y reporte. Por lo tanto, ese resultado histórico no debe presentarse como reproducible desde este ZIP.

Último hito documentado:

- Corrección de lógica específica para `TEAMTAS GENERAL`.
- Refresh de `live_latest` desde la planilla base actual.
- Confirmación de que los CSV expected deben usarse siempre con el Excel baseline que los generó.

## Ejecutar con Docker en Windows

```bash
copy .env.example .env
docker compose up --build
```

Luego abrir:

```text
http://localhost:8000/
http://localhost:8000/admin/
```

## Crear superusuario

```bash
docker compose exec web python manage.py createsuperuser
```

## Importar el Excel de STH

La planilla base oficial para STH debe estar en:

```text
sample_data/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx
```

Importación manual:

```bash
docker compose exec web python manage.py import_sth_excel /app/sample_data/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx --client STH --replace
```

## Validación Excel vs Django

Para validar una batería, usar siempre el Excel baseline que generó sus CSV expected.

Ejemplo `live_latest`:

```bash
docker compose exec web python manage.py validate_excel_battery --import-workbook --workbook /app/sample_data/live_baselines/<STH_LIVE_BASELINE>.xlsx --replace --cases /app/apps/freight/fixtures/live_latest/sth_excel_generated_cases.csv --expected /app/apps/freight/fixtures/live_latest/sth_excel_generated_outputs.csv --components /app/apps/freight/fixtures/live_latest/sth_excel_generated_components.csv --report /app/reports/sth_excel_live_comparison_report.csv
```

Ver más en:

```text
docs/10_excel_django_validation_strategy.md
docs/11_validation_runbook.md
docs/12_validation_findings_log.md
```

## Documentación

Ver carpeta `docs/`.

Documentos principales:

- `docs/02_calculation_flow.md`: flujo de cálculo y reglas especiales por carrier.
- `docs/07_testing_strategy.md`: estrategia de pruebas.
- `docs/10_excel_django_validation_strategy.md`: estrategia Excel vs Django.
- `docs/11_validation_runbook.md`: comandos operativos.
- `docs/12_validation_findings_log.md`: historial de bugs/hallazgos.
- `docs/13_ai_spec_driven_workflow.md`: forma de trabajar con IA y spec-driven development.
- `docs/14_excel_django_traceability_matrix.md`: matriz Excel ↔ Django.
- `docs/15_admin_configuration_dictionary.md`: diccionario de Django Admin.
- `docs/16_user_access_review_and_plan.md`: revisión técnica y plan de usuarios/accesos.
- `business_rules/`: reglas funcionales aprobadas o propuestas.
- `decisions/`: registro de decisiones funcionales.
- `docs/adr/`: decisiones técnicas permanentes.


## Fuentes externas administradas por Django

Django Admin maneja actualmente tres archivos externos:

```text
product_sth.xlsx → referencia/staging, no cambia datos operativos
stock_sth.xlsx   → referencia/staging, no cambia datos operativos
fuel.csv         → cambia fuel solo después de Activate
```

La planilla completa `V2026.R2_Unlocked_STH_Freight_Calculator.xlsx` continúa siendo un import separado mediante `import_sth_excel` y la fuente funcional para validación Excel vs Django.

Ver:

```text
docs/04_imports.md
docs/15_admin_configuration_dictionary.md
```

## Usuarios y acceso — Version 1 implementada

La calculadora ahora requiere sesión Django y usa dos roles:

```text
Customer User → un solo cliente
Internal User → todos los clientes o clientes seleccionados
```

El cliente se valida en el backend para la página, productos y cálculo. Un `client_code` modificado en el navegador no permite acceder a otro cliente.

Django Admin utiliza:

```text
Django Administrator → Internal User / ALL_CLIENTS / grupo autorizado
Technical Superuser  → superusuario nativo para setup y recuperación
```

Después de aplicar las migraciones:

```powershell
docker compose exec web python manage.py setup_access_roles
```

Crear Customer User:

```powershell
docker compose exec -it web python manage.py create_calculator_user `
  --email customer@example.com `
  --role customer `
  --client STH `
  --set-password
```

Crear Django Administrator mínimo:

```powershell
docker compose exec -it web python manage.py create_calculator_user `
  --email admin@example.com `
  --role internal `
  --all-clients `
  --django-admin `
  --set-password
```

Ver `docs/05_authentication_integration.md`, `business_rules/users.md` y ADR 0005.


## Cubic Margin

La calculadora incorpora un campo web `Cubic Margin (%)` con valores enteros de 0 a 20. Es una regla propia de la aplicación y no una entrada original del Excel.

```text
visible ajustado = ROUND_UP(visible original × (1 + margen/100), 3 decimales)
rating ajustado  = visible ajustado + cubic interno de pallets
```

El valor predeterminado es 0 %, por lo que las baterías Excel vs Django existentes no cambian. El código incluye siete pruebas unitarias para 0 %, 10 %, 20 %, redondeo y valores inválidos; la ejecución completa debe confirmarse en Docker porque el diagnóstico del ZIP no terminó la suite.

## Autocomplete data

Los campos de autocompletado de suburbios y productos leen desde PostgreSQL. En una base vacía, el contenedor intenta importar la planilla de muestra después de las migraciones si no existen suburbios cargados.

Primero diagnostica con `showmigrations`, `migrate` y el comando de importación manual. No ejecutes `docker compose down -v` como solución inicial: elimina el volumen de PostgreSQL y todos sus datos. Úsalo solo para recrear deliberadamente un entorno descartable y después de confirmar que no necesitas conservar la base.

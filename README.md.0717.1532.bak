# STH Freight Platform

Aplicación Django/PostgreSQL para migrar la lógica de la planilla `V2026.R2_Unlocked_STH_Freight_Calculator.xlsx` hacia una plataforma web multi-cliente.

## Estado actual validado

El proyecto usa la planilla Excel como fuente de verdad funcional y compara los resultados calculados por Django contra expected outputs generados automáticamente desde Excel.

Validación actual confirmada:

```text
live_latest real 20-case battery: 97 OK / 0 FAIL
random_current 15-case battery:   36 OK / 0 FAIL
```

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
- `docs/adr/`: decisiones técnicas permanentes.

## Autocomplete data

English: The suburb and product autocomplete fields read from PostgreSQL. On a clean Docker volume, the container now imports the sample workbook automatically after migrations if no suburbs exist. If you already had an old database volume, run `docker compose down -v` once so the database is recreated and the import can run.

Español: Los campos de autocompletado de suburbios y productos leen datos desde PostgreSQL. En un volumen Docker limpio, el contenedor importa automáticamente la planilla de ejemplo después de las migraciones si no existen suburbios cargados. Si ya tenías un volumen anterior, ejecuta `docker compose down -v` una vez para recrear la base de datos y permitir la importación.

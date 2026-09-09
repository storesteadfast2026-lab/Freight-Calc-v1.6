# AI Spec-Driven Workflow

## Purpose

This project is developed with AI assistance, but the source of truth remains the code, the Excel workbook, generated fixtures, and validation reports.

## Rules for AI-assisted changes

Before changing calculation logic:

1. Identify the Excel source sheet/cells or imported data behind the behavior.
2. Create or identify a failing Excel-vs-Django case.
3. Explain the current Django behavior and the expected Excel behavior.
4. Patch the smallest reasonable part of the code.
5. Run the relevant battery.
6. Update Markdown documentation.

## Required explanation for each calculation change

Each change should state:

```text
File changed:
Reason:
Excel evidence:
Django behavior before:
Django behavior after:
Validation command:
Validation result:
Docs updated:
```

## Documentation update policy

After meaningful changes, update at least one of:

- `docs/02_calculation_flow.md`
- `docs/07_testing_strategy.md`
- `docs/09_troubleshooting.md`
- `docs/11_validation_runbook.md`
- `docs/12_validation_findings_log.md`
- `docs/adr/`

## Do not rely on chat memory only

Important project decisions must be written to Markdown so a future chat can continue from the ZIP/project files without losing context.

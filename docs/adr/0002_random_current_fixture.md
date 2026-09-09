# ADR 0002 - Use `random_current` as the reusable random test workspace

## Status

Accepted.

## Context

During random validation, several folders such as `random_5`, `random_30`, and other count-specific names were created. This made the workflow harder to repeat and easier to confuse.

## Decision

Use a single fixed workspace for the current random validation run:

```text
app/apps/freight/fixtures/random_current
generated_excel_baselines/random_current
sample_data/live_baselines/random_current
reports/random_current
```

File names remain fixed:

```text
sth_excel_random_cases.csv
sth_excel_random_outputs.csv
sth_excel_random_components.csv
sth_excel_random_comparison_report.csv
```

## Consequences

- Each new random test overwrites the previous random_current data.
- To preserve evidence, copy reports/manifests to `_OK` or date-stamped files.
- The number of cases is controlled by generator input, not by folder name.

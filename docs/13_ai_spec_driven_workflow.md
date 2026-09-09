# AI Spec-Driven Workflow

## Purpose

This project is developed with AI assistance, but no AI-generated statement becomes a business rule merely because a draft labels it “Approved”, “Accepted” or “Confirmed”.

## Source-of-truth hierarchy

Use this order:

1. Explicitly approved files in `business_rules/`.
2. Accepted entries in `decisions/`.
3. Accepted ADRs in `docs/adr/`.
4. Current code and migrations.
5. Automated tests and runtime evidence.
6. Excel workbook and Excel-vs-Django reports for calculation behaviour.
7. Other explanatory Markdown.

For calculation logic, Excel remains the functional source of truth. For web-only features such as users and permissions, approved business rules and decisions are the source of truth.

## Required statuses

New rules and decisions must use:

```text
CONFIRMED / ACCEPTED
PROPOSED
PENDING
REJECTED
```

Do not silently convert a proposal into an accepted requirement.

## Rules for AI-assisted changes

Before changing calculation logic:

1. Identify the Excel source sheet/cells or imported data.
2. Create or identify a failing Excel-vs-Django case.
3. Explain Django behaviour and Excel behaviour.
4. Patch the smallest reasonable code area.
5. Run the relevant battery with the matching baseline.
6. Update Markdown documentation.

Run any battery that imports with `--replace` in an isolated PostgreSQL
database and include `--fail-on-difference`. A report file alone is not proof
that the command returned failure when mismatches existed.

Before changing web-only behaviour such as users/access:

1. Update `business_rules/` with confirmed/proposed rules.
2. Record the decision in `decisions/` or a proposed ADR.
3. Inspect current models, middleware, views and permissions.
4. Identify security and migration effects.
5. Implement one phase at a time.
6. Add backend authorisation tests before UI-only tests.
7. Update operational and troubleshooting documentation.

## Required explanation for each change

```text
File changed:
Reason:
Source evidence:
Behaviour before:
Behaviour after:
Validation command:
Validation result:
Docs updated:
```

## Documentation update policy

After meaningful changes, update the relevant files among:

- `business_rules/` (canonical business rules);
- `decisions/functional_decisions.md` (canonical functional decisions);
- `docs/02_calculation_flow.md`;
- `docs/04_imports.md`;
- `docs/05_authentication_integration.md`;
- `docs/07_testing_strategy.md`;
- `docs/09_troubleshooting.md`;
- `docs/11_validation_runbook.md`;
- `docs/12_validation_findings_log.md`;
- `docs/14_excel_django_traceability_matrix.md`;
- `docs/15_admin_configuration_dictionary.md`;
- `docs/20_ai_project_continuation_prompt.md` when a durable workflow, path, source hierarchy or structural project status changes;
- `docs/adr/`.

## Review ZIP rule

Future AI review ZIPs must include:

```text
app/
tools/
docs/
business_rules/
decisions/
tests/
reports/ when requested
controlled reference files
runtime diagnostics
```

## Reusable continuation prompt

The canonical prompt for starting a new AI-assisted project session is:

```text
docs/20_ai_project_continuation_prompt.md
```

It contains the current project path, source hierarchy, fixed battery locations, known package limitations, required response format and the distinction between snapshot evidence and permanent rules. Update that prompt only after updating the canonical documentation and retained evidence.

## Do not rely on chat memory only

Important project decisions must be stored in the repository so a future review can continue from the files without reconstructing prior conversations.

## Canonical documentation locations

Use only these files as normative sources:

```text
business_rules/*.md
decisions/functional_decisions.md
docs/adr/*.md
```

Files under `docs/business rules/` and `docs/decisions/` are compatibility pointers only. A placeholder or older duplicate must never override a canonical file.

## Runtime-evidence wording

Use these distinctions consistently:

```text
Implemented in source     = code is present.
Runtime verified          = the named command completed successfully and evidence is retained.
Reproducible from package = all required fixtures, baseline and report are included.
Pending                   = required evidence or specification does not exist yet.
```

Do not describe code as release-verified when the captured test suite did not complete.

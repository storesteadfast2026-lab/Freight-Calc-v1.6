# Documentation and AI Prompt Changelog

**Version:** 0728.1256  
**Date:** 2026-07-28 12:56 Australia/Adelaide

## Scope

Documentation-only update of the STH Freight Calculator project package. No Django code, migrations, templates, styles, fixtures, reports, spreadsheets or business formulas were changed.

This version includes all documentation normalization from version `0728.1230` and adds the updated canonical prompt for future AI-assisted development sessions.

## Documentation normalization retained

1. Canonical sources remain `business_rules/*.md`, `decisions/functional_decisions.md` and `docs/adr/*.md`.
2. Historical duplicate paths remain compatibility pointers only.
3. Unknown Excel behavior remains explicitly pending instead of being converted into assumed business rules.
4. Document, ADR and decision numbering remains normalized.
5. The active project path remains `C:\Docker-Projects\Freight-Calc-Nuevo`.
6. Review-package limitations remain distinguished from the full project repository.

## Prompt update completed

1. Added `docs/20_ai_project_continuation_prompt.md` as the canonical reusable prompt.
2. Replaced the old assumption that every ZIP contains an operational `sample_data/` tree with an explicit distinction between:
   - controlled review copy under `reference_files/`;
   - operational workbook under `sample_data/` in the full project.
3. Added the mandatory documentation review order and canonical source hierarchy.
4. Added explicit evidence statuses: implemented, runtime verified, reproducible, partial and pending.
5. Preserved the fixed `live_latest` and `random_current` paths and filenames.
6. Recorded `live_latest` results as dated snapshot evidence, not a permanent guarantee.
7. Recorded that `random_current` was incomplete in the reviewed package.
8. Included the confirmed zone, postcode, visible cubic and component-comparison rules.
9. Updated the prompt with the implemented user/access architecture and pending SMTP work.
10. Listed open functional areas where formulas must not be inferred.
11. Added mandatory change-reporting, PowerShell, documentation and versioning requirements.
12. Added maintenance rules so future temporary results do not make the prompt stale again.

## Files added or updated in this prompt revision

- `docs/20_ai_project_continuation_prompt.md` — added.
- `docs/13_ai_spec_driven_workflow.md` — linked the canonical prompt and its maintenance rule.
- `docs/19_documentation_status.md` — registered the prompt as a canonical project source.
- `README.md` — added the prompt to the document index and usage section.

## Intentionally still pending

- exact overlength formula;
- complete `random_current` evidence set;
- complete Django runtime test capture;
- retained targeted TEAMTAS GENERAL baseline case;
- quotation specification/model;
- email invitation/password-reset delivery;
- directed mixed P/C, quantity, hand-unload and warehouse-handling validation.

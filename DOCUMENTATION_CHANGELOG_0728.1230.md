# Documentation Finalization Changelog

**Version:** 0728.1230  
**Date:** 2026-07-28 12:30 Australia/Adelaide

## Scope

Documentation-only normalization of the supplied STH Freight Calculator review package. No application code, migrations, templates, styles, fixtures, reports or spreadsheets were changed.

## Completed

1. Defined canonical sources for business rules, decisions and ADRs.
2. Replaced contradictory duplicate documents with compatibility pointers.
3. Completed Product and Rate rule documents using only delivered code/documentation evidence.
4. Converted the Quotation placeholder into an explicit pending-scope document.
5. Updated obsolete authentication traceability from proposed to implemented-in-source/runtime-recheck.
6. Resolved numbering collisions:
   - login document moved from 17 to 18;
   - validation-baseline ADR moved from 0002 to 0008;
   - integrated UserAdmin and FreightCalculator decisions assigned DEC-014 and DEC-015.
7. Added ADR 0009 and `docs/19_documentation_status.md`.
8. Corrected the active project path to `C:\Docker-Projects\Freight-Calc-Nuevo`.
9. Documented that the review ZIP is not a standalone Docker deployment package.
10. Recorded unresolved formulas as pending evidence rather than inventing business logic.

## Intentionally still pending

- exact overlength formula;
- complete `random_current` evidence set;
- complete Django runtime test capture;
- quotation specification/model;
- email invitation/password-reset delivery;
- directed mixed P/C, hand-unload and warehouse-handling validation.

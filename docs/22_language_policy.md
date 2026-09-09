# Project Language Policy

**Status:** CURRENT  
**Reviewed:** 2026-08-19 08:10 Australia/Adelaide  
**Applies to:** application text, developer documentation, code comments and docstrings

## Required language

The application targets Australia. Use Australian English for:

- user-facing labels, messages and help text;
- developer-facing messages and operational instructions;
- project documentation, including Markdown and Word files;
- code comments and docstrings.

Use Australian spelling and terminology where applicable, including `behaviour`,
`authorisation`, `organisation`, `normalise`, `centred` and `synchronisation`.

## Spanish exception

`docs/20_ai_project_continuation_prompt.md` is the only project document that is
intentionally maintained in Spanish. It is a reusable prompt for Spanish-speaking
operators and must remain in neutral Spanish.

## Text that must remain exact

Do not translate or respell exact technical values, including:

- code identifiers, model and field names, paths, commands and URLs;
- carrier, service, worksheet and workbook names;
- stored business codes and external-system values;
- third-party product labels, such as Django's `Authentication and Authorization`.

## Safe maintenance rule

Language-only maintenance of comments and docstrings must not change executable
logic, runtime values, request or response contracts, database behaviour or test
expectations. Any runtime text change is an application change and must be reviewed
separately.

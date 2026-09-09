# Functional Decisions Log

**Project:** STH Freight Calculator  
**Last review:** 2026-07-28  
**Canonical location:** `decisions/functional_decisions.md`

## DEC-001 — Calculator roles

- **Status:** Accepted and implemented.
- **Decision:** Version 1 includes only `Customer User` and `Internal User`.

## DEC-002 — Calculator and Django Admin separation

- **Status:** Accepted and implemented.
- **Decision:** Django Admin is separate authorization. Customer Users cannot access it.

## DEC-003 — Minimum Django Admin profiles

- **Status:** Accepted and implemented in source.
- **Decision:** Use the protected groups `Administrators`, `Customers` and `Steadfast Users`, plus the exceptional native Super User account `super`.

## DEC-004 — Existing Django user model

- **Status:** Accepted and implemented.
- **Decision:** Keep built-in `auth.User`; normalized email is stored in `username` and `email` for calculator users.

## DEC-005 — Calculator access profile

- **Status:** Accepted and implemented.
- **Decision:** `CalculatorUserProfile` stores role, scope, single client, selected clients and calculator entitlement.

## DEC-006 — Quotation permissions

- **Status:** Pending.
- **Decision:** No quotation permission or lifecycle rule is approved until a persistent Quotation model and separate specification exist.

## DEC-007 — Three Django Admin source files

- **Status:** Accepted and implemented in source.
- **Decision:** Product and Stock remain reference-only staging. Fuel changes operational values only after explicit activation.

## DEC-008 — Review-package contents

- **Status:** Accepted.
- **Decision:** Review packages include `business_rules/`, `decisions/`, `docs/`, code, tests, controlled reference files and captured diagnostics. A review package may still be non-runnable when required runtime-only files are omitted; that limitation must be stated explicitly.

## DEC-009 — Administrator scope and privilege escalation

- **Status:** Accepted and implemented in source.
- **Decision:** Members of `Administrators` must be Internal User / All clients. User, Group, Permission and superuser management remain Super-User-only.

## DEC-010 — Import action permissions

- **Status:** Accepted and implemented in source.
- **Decision:** Validation, Fuel activation, Fuel rollback and external-file download use distinct custom Django permissions instead of relying only on `is_staff`.

## DEC-011 — Initial password workflow

- **Status:** Partially implemented.
- **Decision:** User creation and secure interactive password setup are implemented. Email invitation and password-reset delivery remain pending SMTP configuration and end-to-end tests.

## DEC-012 — Calculator access errors use the login interface

- **Status:** Accepted and implemented in source on 2026-07-24.
- **Decision:** Calculator entitlement is checked before retaining a login session. Public entitlement failures return to the login card with a generic message instead of exposing internal profile details.
- **Security:** CSRF remains enabled; no `csrf_exempt` workaround is permitted.

## DEC-013 — Supplied login design is the visual baseline

- **Status:** Accepted and implemented in source on 2026-07-24.
- **Decision:** Preserve the supplied login behavior: the complete card uses `fadeInDown`, and logo/fields use the original delayed fade sequence.
- **Boundary:** Visual changes must not replace the Django POST form, CSRF token, server-side messages, entitlement validation or client authorization.

## DEC-014 — Integrated user administration

- **Status:** Accepted and implemented in source on 2026-07-27.
- **Decision:** Manage identity and optional `CalculatorUserProfile` in `Authentication and Authorization > Users`. Hide the standalone profile from the normal Admin index while retaining direct Technical-Superuser diagnostic access.

## DEC-015 — Hide FreightCalculator from Django Admin

- **Status:** Accepted and implemented in source on 2026-07-27.
- **Decision:** Keep the `FreightCalculator` model and database table, but do not register it in Django Admin while it has no confirmed operational effect on calculations.
- **Reversibility:** Admin registration can be restored if the model later becomes operationally meaningful.

## DEC-016 — Documentation canonicalization

- **Status:** Accepted on 2026-07-28.
- **Decision:** `business_rules/`, `decisions/functional_decisions.md`, numbered `docs/` files and uniquely numbered ADRs are canonical. Duplicate historical paths remain only as explicit pointers and must not contain competing rules.

## DEC-017 — Group-only user permissions

- **Status:** Accepted and implemented in source on 2026-07-30.
- **Decision:** User administration does not expose individual permissions. Every normal user receives one protected primary group: `Administrators`, `Customers` or `Steadfast Users`.
- **Mapping:** The primary group synchronises calculator role, client scope and staff status. Client isolation remains stored in `CalculatorUserProfile`.
- **Super User:** The native account `super` remains outside the protected-group requirement and receives permissions through `is_superuser`.
- **Transition safety:** Existing individual permissions are reported by `setup_access_roles` but are not silently deleted.

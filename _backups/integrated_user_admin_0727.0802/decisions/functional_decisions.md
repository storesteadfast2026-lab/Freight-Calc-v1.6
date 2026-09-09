# Functional Decisions Log

**Project:** STH Freight Calculator  
**Last review:** 2026-07-22

## DEC-001 — Calculator roles

- **Status:** Accepted and implemented.
- **Decision:** Version 1 includes only `Customer User` and `Internal User`.

## DEC-002 — Calculator and Django Admin separation

- **Status:** Accepted and implemented.
- **Decision:** Django Admin is separate authorization. Customer Users cannot access it.

## DEC-003 — Minimum Django Admin profiles

- **Status:** Accepted and implemented.
- **Decision:** Use one `Django Administrator` group plus exceptional native Technical Superusers.

## DEC-004 — Existing Django user model

- **Status:** Accepted and implemented.
- **Decision:** Keep built-in `auth.User`; normalized email is stored in `username` and `email` for calculator users.

## DEC-005 — Calculator access profile

- **Status:** Accepted and implemented.
- **Decision:** `CalculatorUserProfile` stores role, scope, single client, selected clients and calculator entitlement.

## DEC-006 — Quotation permissions

- **Status:** Pending.
- **Reason:** There is no persistent Quotation model.

## DEC-007 — Three Django Admin source files

- **Status:** Confirmed.
- **Decision:** Product and Stock remain reference-only staging. Fuel changes operational values only after explicit activation.

## DEC-008 — Review-package contents

- **Status:** Accepted.
- **Decision:** Review packages include `business_rules/`, `decisions/`, `docs/`, code, tests and controlled reference files.

## DEC-009 — Administrator scope and privilege escalation

- **Status:** Accepted and implemented.
- **Decision:** Normal Django Administrators must be Internal User / All clients. User/group/permission and superuser management remain Technical-Superuser-only.

## DEC-010 — Import action permissions

- **Status:** Accepted and implemented.
- **Decision:** Validation, Fuel activation, Fuel rollback and external-file download use distinct custom Django permissions instead of relying only on `is_staff`.

## DEC-011 — Initial password workflow

- **Status:** Partially implemented.
- **Decision:** User creation and secure interactive password setup are implemented. Email invitation/password-reset delivery remains a later phase pending SMTP configuration and end-to-end testing.

## DEC-012 — Calculator access errors use the login interface

- **Status:** Accepted and implemented on 2026-07-24.
- **Decision:** Valid credentials are checked for calculator entitlement before a login session is created. Front-end entitlement failures return to the login card with a generic message instead of exposing internal profile details in a plain 403 response.
- **Security:** CSRF remains enabled; no `csrf_exempt` workaround is permitted.

## DEC-013 — Supplied login design is the visual baseline

- **Status:** Accepted and implemented on 2026-07-24.
- **Decision:** Preserve the supplied login behavior: the complete card uses `fadeInDown`, and logo/fields use the original delayed fade sequence.
- **Boundary:** Visual changes must not replace the Django POST form, CSRF token, server-side messages, entitlement validation or client authorization.
- **Implementation:** Keep login-specific styling in `app/static/css/login.css` to avoid affecting the calculator UI.

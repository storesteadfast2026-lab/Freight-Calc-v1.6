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

## DEC-012 - Prevent account enumeration during calculator login

- **Status:** Accepted and implemented.
- **Decision:** Validate calculator entitlement before completing session login and display a single generic rejection message for all failed or unauthorised login states.


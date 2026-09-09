# ADR 0006: Integrated user and calculator-access administration

- Status: Accepted; group terminology and User form amended by ADR 0010
- Date: 2026-07-27

## Context

Django's built-in `User` controls identity, password, active status, staff status, superuser status, groups and permissions. Calculator access is stored separately in `CalculatorUserProfile`.

Creating a user through Django Admin previously created only `auth.User`. The calculator profile was easy to miss, leaving a valid Django account unable to use the calculator.

## Decision

Use `Authentication and Authorization > Users` as the normal user-management
workflow. The original inline-profile design was later replaced by ADR 0010's
primary-group form while retaining the same `CalculatorUserProfile` data model.

The standalone profile model remains registered for native Super User
diagnostics by direct URL, but is hidden from the main Admin menu. A blank
calculator block creates no profile.

## Security boundaries

- User management remains native-Super-User-only in version 1.
- `Administrators` retains operational model permissions but no User, Group or Permission management.
- Active, Staff, Superuser and Calculator access remain independent.
- Server-side model and form validation remain authoritative.

## Consequences

- Account and calculator access can be configured in one screen.
- Technical-only superusers may exist without calculator access.
- No database migration is required.

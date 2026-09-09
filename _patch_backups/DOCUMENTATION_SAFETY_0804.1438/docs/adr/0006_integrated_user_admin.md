# ADR 0006: Integrated user and calculator-access administration

- Status: Accepted
- Date: 2026-07-27

## Context

Django's built-in `User` controls identity, password, active status, staff status, superuser status, groups and permissions. Calculator access is stored separately in `CalculatorUserProfile`.

Creating a user through Django Admin previously created only `auth.User`. The calculator profile was easy to miss, leaving a valid Django account unable to use the calculator.

## Decision

Use `Authentication and Authorization > Users` as the normal user-management workflow. Embed the existing one-to-one `CalculatorUserProfile` as an optional inline block inside the User add/change screen.

The standalone profile model remains registered for Technical Superuser diagnostics by direct URL, but is hidden from the main Admin menu. A blank calculator block creates no profile.

## Security boundaries

- User management remains Technical-Superuser-only in version 1.
- `Django Administrator` retains operational model permissions but no User, Group or Permission management.
- Active, Staff, Superuser and Calculator access remain independent.
- Server-side model and form validation remain authoritative.

## Consequences

- Account and calculator access can be configured in one screen.
- Technical-only superusers may exist without calculator access.
- No database migration is required.

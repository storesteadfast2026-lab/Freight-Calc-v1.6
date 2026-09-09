# ADR 0005 — User Identity and Access Model for Version 1

- **Status:** Accepted and implemented.
- **Date:** 2026-07-22.

## Context

The calculator previously had no session-authenticated user scope. Browser-supplied `client_code` could select the client, while custom Django Admin actions relied too broadly on staff status.

The project already contains migrations and foreign keys referencing `settings.AUTH_USER_MODEL`. Replacing the built-in user now would add unnecessary migration risk.

## Decision

1. Keep Django built-in `auth.User`.
2. Store normalized calculator-user email in `username` and `email`.
3. Add `CalculatorUserProfile` in `authentication_gateway`.
4. Use only `CUSTOMER_USER` and `INTERNAL_USER` calculator roles.
5. Use `SINGLE_CLIENT`, `SELECTED_CLIENTS` and `ALL_CLIENTS` scopes as defined by role.
6. Protect calculator page and APIs with Django sessions.
7. Resolve the effective client in backend services; never trust unrestricted browser `client_code`.
8. Use one `Django Administrator` group for normal administration.
9. Require normal administrators to be Internal User / All clients.
10. Keep User, Group, Permission and superuser administration exclusive to Technical Superusers.
11. Protect import validation, Fuel activation, Fuel rollback and download through custom permissions.
12. Defer quotation permissions until quotation persistence exists.

## Implemented components

```text
apps.authentication_gateway.models.CalculatorUserProfile
apps.authentication_gateway.services
apps.authentication_gateway.decorators
apps.authentication_gateway.middleware.DjangoAdminAccessMiddleware
setup_access_roles management command
create_calculator_user management command
Django login/logout routes and templates
server-authorized freight views
custom ExternalDataFile permissions
```

## Consequences

### Positive

- Avoids a risky custom-user migration.
- Uses Django password hashing, sessions and standard authentication.
- Enforces multi-client scope in backend code.
- Prevents a staff flag alone from granting operational Admin access.
- Creates a minimum model that can be split into more groups later.

### Negative

- Built-in `User.email` is not unique; Version 1 uniqueness relies on `username=email` for users created through the command.
- Calculator user administration remains Technical-Superuser-controlled.
- Invitation email remains pending.

## Verification requirement

Run migrations, access setup, authentication tests, freight tests and import tests in Docker before deployment. Static review alone is not sufficient for release approval.

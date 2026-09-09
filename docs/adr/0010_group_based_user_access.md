# ADR 0010 — Group-based User access

- **Status:** Accepted and implemented in source.
- **Date:** 2026-07-30.

## Context

Django's default User form exposed Groups and individual User permissions at
the same time. Staff and superuser flags were also editable separately from the
project's calculator profile, allowing confusing or contradictory combinations.

## Decision

Normal users receive exactly one protected primary group:

```text
Administrators
Customers
Steadfast Users
```

| Group | Calculator role/scope | Staff |
|---|---|---:|
| Administrators | Internal User / All clients | Yes |
| Customers | Customer User / Single client | No |
| Steadfast Users | Internal User / All clients | No |

Individual User permissions are removed from User administration. Operational
permissions are configured on Groups. The native Super User account `super`
remains outside the primary-group requirement.

## Security boundaries

- Administrators do not receive User, Group, Permission or superuser management.
- Customer client selection remains explicit and backend-enforced.
- The Super User's calculator profile is optional.
- Existing individual permissions are reported during setup and are not
  silently deleted.

## Consequences

- User setup becomes one primary-group selection plus Customer client when
  required.
- `is_staff` is derived from Administrators membership.
- No database schema migration is required.
- Quotation permissions remain pending until a Quotation model and approved
  lifecycle exist.

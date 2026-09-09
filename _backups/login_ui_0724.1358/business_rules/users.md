# Business Rules — Users and Access

**Status:** CONFIRMED and implemented for Version 1  
**Last review:** 2026-07-22  
**Scope:** Freight calculator and Django Admin access.

## USR-001 — Calculator roles

Version 1 has only two calculator roles:

- `CUSTOMER_USER` — Customer User.
- `INTERNAL_USER` — Internal User.

Django Admin access is separate from the calculator role.

## USR-002 — Customer User

A Customer User:

- belongs to exactly one active client;
- uses `SINGLE_CLIENT` scope;
- cannot be `is_staff`;
- cannot select or submit another client;
- cannot access Django Admin.

The server must ignore or reject any browser request that tries to use another client.

## USR-003 — Internal User

An Internal User uses one of these scopes:

- `ALL_CLIENTS`; or
- `SELECTED_CLIENTS` with at least one active client.

The client selector may show only clients returned by the backend authorization service.

## USR-004 — Login identity

Calculator users use normalized lowercase email in both:

```text
User.username
User.email
```

`User.username` remains the unique database login identifier. Existing Technical Superusers may retain non-email usernames.

## USR-005 — Account status

`User.is_active` is the account activation source of truth. `CalculatorUserProfile.calculator_access` independently controls calculator entitlement; it does not replace `is_active`.

## USR-006 — Minimum Django Admin model

### Django Administrator

A normal administrator must satisfy all conditions:

- `is_staff=True`;
- `is_superuser=False`;
- calculator role `INTERNAL_USER`;
- scope `ALL_CLIENTS`;
- enabled calculator access;
- membership in group `Django Administrator`.

The group receives operational model permissions and explicit import-action permissions. It does not receive User, Group, Permission or superuser-management permissions.

### Technical Superuser

A Technical Superuser is a native Django superuser reserved for setup, recovery and exceptional technical administration. It is not a calculator business role.

## USR-007 — Backend authorization boundary

The following routes require an authenticated user with an enabled calculator profile:

```text
/
/api/suburbs/
/api/products/
/api/calculate/
```

Client authorization is resolved centrally in `apps.authentication_gateway.services`.

## USR-008 — User creation

Version 1 creates calculator users through the Technical Superuser-controlled management command:

```text
python manage.py create_calculator_user
```

The command creates an unusable password unless `--set-password` is used interactively. Sending passwords by email is prohibited.

## USR-009 — Quotation permissions

Quotation draft, finalization, PDF, email and ownership rules remain `PENDING` because no persistent Quotation model exists.

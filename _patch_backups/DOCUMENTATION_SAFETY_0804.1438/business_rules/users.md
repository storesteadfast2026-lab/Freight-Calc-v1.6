# Business Rules — Users and Access

**Status:** CONFIRMED and implemented for Version 1  
**Last review:** 2026-07-28  
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

`User.username` remains the unique database login identifier. The native Super User account may retain the non-email username `super`.

## USR-005 — Account status

`User.is_active` is the account activation source of truth. `CalculatorUserProfile.calculator_access` independently controls calculator entitlement; it does not replace `is_active`.

## USR-006 — Minimum Django Admin model

### Administrator

A normal administrator must satisfy all conditions:

- `is_staff=True`;
- `is_superuser=False`;
- calculator role `INTERNAL_USER`;
- scope `ALL_CLIENTS`;
- enabled calculator access;
- membership in group `Administrators`.

The group receives operational model permissions and explicit import-action permissions. It does not receive User, Group, Permission or superuser-management permissions.

### Super User

A Super User is a native Django superuser reserved for setup, recovery and exceptional administration. The designated account name is `super`. It is not a calculator business role and does not require a primary access group.

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

Version 1 creates calculator users through the Super-User-controlled management command:

```text
python manage.py create_calculator_user
```

The command creates an unusable password unless `--set-password` is used interactively. Sending passwords by email is prohibited.

## USR-009 — Quotation permissions

Quotation draft, finalization, PDF, email and ownership rules remain `PENDING` because no persistent Quotation model exists.

## USR-010 — Generic login rejection

All rejected calculator login attempts must return the same visible message, regardless of whether the username exists, the password is valid, the user is active or a calculator profile exists. Internal logs may record the specific reason. A rejected attempt must not create an authenticated session.



<!-- USER_ADMIN_INTEGRATION_0727.0802 -->
## BR-USER-ADMIN-001 — One normal administration workflow

The normal workflow is `Authentication and Authorization > Users`. Creating or enabling `auth.User` alone does not grant calculator access. A blank calculator block must not create access automatically.

## BR-USER-GROUP-001 — Group-only permission assignment

Normal users must use exactly one protected primary access group:

```text
Administrators
Customers
Steadfast Users
```

Individual `User.user_permissions` are not editable from User administration.
Operational Django permissions are assigned only to Groups.

- `Administrators`: Internal User, All clients, calculator enabled and `is_staff=True`.
- `Customers`: Customer User, Single client, calculator enabled and `is_staff=False`.
- `Steadfast Users`: Internal User, All clients, calculator enabled and `is_staff=False`.

Only the native Super User can manage Users, Groups and group permissions.

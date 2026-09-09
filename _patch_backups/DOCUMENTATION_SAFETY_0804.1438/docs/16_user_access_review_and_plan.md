# User Access Version 1 — Implementation Record

**Implemented:** 2026-07-22  
**Release state:** Implemented in source; migrations are captured as applied and `manage.py check` passed. Full/targeted test execution remains required because the packaged suite stopped while creating the test database.

## Implemented

- Customer User and Internal User profile model.
- Single, selected and all-client scopes.
- Login and POST logout.
- Protected calculator page and APIs.
- Server-side client selection and tampering rejection.
- Internal client selector populated only from authorized clients.
- Protected `Administrators`, `Customers` and `Steadfast Users` group command.
- Super User remains native Django superuser under the designated account `super`.
- Middleware enforcing Internal User / All clients / group membership for normal staff.
- Explicit import permissions for validation, Fuel activation, Fuel rollback and download.
- Read-only audit/source-row Admin access through model permissions.
- User creation management command.
- Authentication/access tests added.

## Not implemented

- Email invitations and password-reset email delivery (pending SMTP configuration and end-to-end tests).
- User management by Administrators; Version 1 keeps it Super-User-only by decision.
- Object-level selected-client scoping inside Django Admin.
- Quotation persistence and quotation permissions.

## Release checklist

```powershell
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py setup_access_roles
docker compose exec web python manage.py check
docker compose exec web python manage.py test apps.authentication_gateway apps.freight apps.imports -v 2
```

Then manually verify:

1. Anonymous calculator access redirects to login.
2. Customer User cannot change client through URL, product endpoint or calculate payload.
3. Internal User sees only permitted clients.
4. Internal User without Admin group cannot enter Django Admin.
5. Administrator cannot manage Users, Groups or Permissions.
6. Product and Stock imports remain reference-only.
7. Fuel validation, activation and rollback follow separate permissions.
8. Existing Excel-vs-Django baseline remains unchanged.


<!-- USER_ADMIN_INTEGRATION_0727.0802 -->
## Implemented: integrated User administration

User and CalculatorUserProfile remain separate database records but are managed in one group-based Admin screen. Version 1 keeps user administration restricted to the Super User.

## 2026-07-30 group-based administration update

- Individual User permissions are removed from the User form.
- One primary group drives calculator role, client scope and staff status.
- `Administrators` receives operational Admin permissions.
- `Customers` requires one active client and cannot enter Django Admin.
- `Steadfast Users` receives internal calculator access without Django Admin.
- No schema migration is required.

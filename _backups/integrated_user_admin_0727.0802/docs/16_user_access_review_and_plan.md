# User Access Version 1 — Implementation Record

**Implemented:** 2026-07-22  
**Release state:** Code complete; Docker migration and full test execution required.

## Implemented

- Customer User and Internal User profile model.
- Single, selected and all-client scopes.
- Login and POST logout.
- Protected calculator page and APIs.
- Server-side client selection and tampering rejection.
- Internal client selector populated only from authorized clients.
- Minimum `Django Administrator` group command.
- Technical Superuser remains native Django superuser.
- Middleware enforcing Internal User / All clients / group membership for normal staff.
- Explicit import permissions for validation, Fuel activation, Fuel rollback and download.
- Read-only audit/source-row Admin access through model permissions.
- User creation management command.
- Authentication/access tests added.

## Not implemented

- Email invitations and password-reset email delivery.
- Restricted user-management UI for normal administrators.
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
5. Django Administrator cannot manage Users, Groups or Permissions.
6. Product and Stock imports remain reference-only.
7. Fuel validation, activation and rollback follow separate permissions.
8. Existing Excel-vs-Django baseline remains unchanged.

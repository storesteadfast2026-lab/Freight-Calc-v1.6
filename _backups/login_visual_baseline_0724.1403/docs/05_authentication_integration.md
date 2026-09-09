# Authentication and Authorization Integration

## 1. Boundary

Excel has no users or permissions. Authentication and client isolation are web-platform rules and must not be inferred from spreadsheet formulas.

## 2. Version 1 implementation

The application uses:

- Django built-in `auth.User`;
- Django sessions and `AuthenticationMiddleware`;
- `CalculatorUserProfile` for calculator role and client scope;
- centralized authorization in `apps.authentication_gateway.services`;
- `DjangoAdminAccessMiddleware` for the minimum Admin model;
- standard login/logout URLs under `/accounts/`.

`ExternalAuthMiddleware` remains only as a compatibility hook and does not authenticate users.

## 3. Profile model

```text
CalculatorUserProfile
├── user: OneToOne(auth.User)
├── role: CUSTOMER_USER | INTERNAL_USER
├── client_scope: SINGLE_CLIENT | ALL_CLIENTS | SELECTED_CLIENTS
├── client: one Client for Customer User
├── allowed_clients: selected clients for Internal User
├── calculator_access
├── created_at
└── updated_at
```

A database check constraint enforces valid role/scope/single-client combinations. Admin forms and management commands enforce M2M and staff rules.

## 4. Authorization service

```python
get_calculator_profile(user)
allowed_clients_for(user)
resolve_authorized_client(user, requested_client_code=None)
is_django_administrator(user)
```

The freight views call this service before loading products, selecting addresses or invoking `FreightCalculatorService`.

## 5. Routes

```text
/accounts/login/   Django session login
/accounts/logout/  POST logout
/                  authenticated calculator page
/api/suburbs/      authenticated autocomplete
/api/products/     authenticated and client-scoped
/api/calculate/    authenticated and client-scoped
/admin/            Technical Superuser or approved Django Administrator
```

Anonymous API calls return JSON HTTP 401. Authenticated users without calculator entitlement receive HTTP 403.

## 6. Commands

Create/update the minimum group after migrations:

```powershell
docker compose exec web python manage.py setup_access_roles
```

Create Customer User:

```powershell
docker compose exec -it web python manage.py create_calculator_user `
  --email customer@example.com `
  --role customer `
  --client STH `
  --set-password
```

Create Internal User for selected clients:

```powershell
docker compose exec -it web python manage.py create_calculator_user `
  --email internal@example.com `
  --role internal `
  --allowed-client STH `
  --set-password
```

Create minimum Django Administrator:

```powershell
docker compose exec web python manage.py setup_access_roles

docker compose exec -it web python manage.py create_calculator_user `
  --email admin@example.com `
  --role internal `
  --all-clients `
  --django-admin `
  --set-password
```

Create Technical Superuser:

```powershell
docker compose exec -it web python manage.py createsuperuser
```

## 7. Pending phase

Email invitation/password setup is not yet implemented end to end. SMTP settings and token-delivery tests are required before enabling invitations.

## LOGIN-SECURITY-0724.1358 - Generic calculator login response

The calculator login validates Django credentials and calculator entitlement before creating the session. Unknown user, incorrect password, inactive account, missing profile, disabled calculator access and invalid client scope all use the same browser-visible error. Detailed causes are recorded only in server logs. See `docs/17_login_security_and_ui.md`.


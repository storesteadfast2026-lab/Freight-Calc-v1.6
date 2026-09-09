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

## 8. Login and access messages — 2026-07-24

All front-end authentication feedback is rendered inside `registration/login.html`.

Confirmed behavior:

- invalid username/password uses one generic credential message;
- valid credentials without calculator entitlement do not create a login session;
- an old authenticated session without a calculator profile is cleared and redirected to login;
- the browser never receives the internal text `This user does not have a calculator access profile.` as a plain page;
- front-end CSRF failures use the same login-card visual presentation;
- API authentication failures remain JSON (`401` or `403`);
- Django Admin retains its independent CSRF response.

The public access message is intentionally generic:

```text
Your account does not have access to the Freight Calculator.
```

Detailed entitlement reasons remain internal to the authorization service and are not exposed on the public login screen.

## 9. Approved login visual baseline — 2026-07-24

The supplied login HTML/CSS is the visual reference for the authentication screen.
The approved sequence is:

1. the complete login card moves from above to its centered position using `fadeInDown`;
2. the Steadfast Freight logo fades in after 0.4 seconds;
3. username, password and submit controls fade in at 0.6, 0.8 and 1.0 seconds;
4. authentication, entitlement and CSRF messages remain inside the card;
5. the Django POST form, `{% csrf_token %}`, `next` field and server-side validation remain unchanged.

The dedicated stylesheet is `app/static/css/login.css`. It is intentionally separate from `app.css` so login-specific body, card and animation rules do not alter the freight calculator interface.

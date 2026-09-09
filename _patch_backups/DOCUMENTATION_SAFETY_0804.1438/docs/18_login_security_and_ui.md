# Login UI and User Enumeration Protection

**Implemented in source:** 2026-07-24 13:26 Australia/Adelaide  
**Status:** Implementation present in the delivered source; targeted Docker verification remains required because the complete packaged test run did not finish.

## Visual behaviour

The calculator login uses the approved Steadfast reference design:

- blue page background;
- centred white card;
- Steadfast Freight header logo;
- `AUTHORISED ENTRY ONLY` notice;
- email/username and password fields;
- login button with disabled `Signing in…` state;
- inline error message and short shake animation;
- responsive width on phone and desktop;
- Steadfast footer branding.

The supplied prototype JavaScript was not copied because it called `preventDefault()` and always displayed an incorrect-password message. The Django implementation submits a real POST with CSRF protection.

## Security behaviour

These cases return the same browser-visible message:

- unknown username;
- incorrect password;
- inactive account;
- missing calculator profile;
- calculator access disabled;
- invalid role/client scope;
- missing or inactive customer client;
- selected-client internal account with no active allowed client.

Visible response:

```text
The email/username or password is incorrect.
Your account does not have access to that page.
```

The reason is written only to the server log. A rejected login does not create an authenticated session.

## Generic 403

Browser permission failures use `templates/403.html`. API permission failures return:

```json
{"error": "Access denied."}
```

with HTTP 403.

## Files

```text
app/apps/authentication_gateway/forms.py
app/apps/authentication_gateway/views.py
app/apps/authentication_gateway/urls.py
app/apps/authentication_gateway/tests/test_login_security.py
app/templates/registration/login.html
app/templates/403.html
app/static/css/login.css
app/config/urls.py
app/config/settings/base.py
```

## Verification

```powershell
docker compose up -d --build
docker compose exec web python manage.py check
docker compose exec web python manage.py test `
  apps.authentication_gateway.tests.test_login_security `
  -v 2
```

Then manually compare an unknown username, wrong password and valid credentials without a calculator profile. All three must display the identical generic message.

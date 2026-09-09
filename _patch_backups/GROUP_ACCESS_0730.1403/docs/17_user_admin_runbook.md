# User Administration Runbook

## Normal location

```text
Django Admin
-> Authentication and Authorization
-> Users
```

The separate Calculator User Profiles menu is hidden to avoid two normal workflows.

## Customer User

1. Create the Django user and password.
2. In Calculator access, select Enable calculator access.
3. Select Customer User.
4. Select Single client.
5. Select one active client.
6. Leave Allowed clients empty.
7. Do not enable Staff or Superuser.

## Internal User

1. Create the Django user and password.
2. Enable calculator access.
3. Select Internal User.
4. Select All clients or Selected clients.
5. For Selected clients, choose at least one active client.
6. Leave the single Client field empty.

## Technical Superuser

A Technical Superuser may remain without a calculator profile. The Users list must then show Calculator status: Not configured. Configure the calculator block only when that account must also use the calculator.

## Status interpretation

- Active: the Django identity can authenticate.
- Calculator status: the account has an enabled calculator profile.
- Staff status: the account may access Django Admin when authorization permits.
- Superuser: unrestricted Django Admin permissions.
- Not configured: no CalculatorUserProfile exists.
- Disabled: a profile exists but calculator_access is false.

## Troubleshooting order

1. Confirm Active.
2. Confirm the password is usable.
3. Read Calculator status in the Users list.
4. Inspect the Calculator access block.
5. Confirm role and client scope are consistent.
6. Confirm Customer User has one active client.
7. Confirm Internal / Selected clients has at least one active client.

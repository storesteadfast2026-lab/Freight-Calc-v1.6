# Authentication Integration

The Excel file has no login or privilege logic.

The Django project is prepared for a future independent login container through:

- `CALCULATOR_REQUIRE_AUTH`
- `EXTERNAL_AUTH_HEADER`
- `ExternalAuthMiddleware`

Initial mode:

```env
CALCULATOR_REQUIRE_AUTH=0
```

Future protected mode:

```env
CALCULATOR_REQUIRE_AUTH=1
EXTERNAL_AUTH_HEADER=HTTP_X_AUTH_USER
```

Suggested roles:

- Administrator
- Authorized user
- Read-only user

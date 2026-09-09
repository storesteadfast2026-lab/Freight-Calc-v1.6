# Multi-client Strategy

## 1. Current data model

Operational entities already carry Client ownership where required. Version 1 user authorization now adds explicit client scope to each calculator user.

## 2. Customer User

A Customer User is bound to exactly one active Client. The browser may display the client, but it cannot select another client. Backend authorization rejects a different query parameter or JSON `client_code`.

## 3. Internal User

An Internal User has:

- `ALL_CLIENTS`; or
- `SELECTED_CLIENTS` through a many-to-many relation.

The calculator client selector is generated from `allowed_clients_for(user)` and therefore shows only authorized active clients.

## 4. Backend rule

Every client-specific request uses:

```python
resolve_authorized_client(request.user, requested_client_code)
```

The resolved `Client.code`, not the untrusted browser value, is passed to `FreightRequest` and the calculation service.

## 5. Django Admin limitation in Version 1

Normal Django Administrators use `ALL_CLIENTS`. Selected-client Django Admin scoping is intentionally not implemented because it would require object-level query, relation and custom-action filtering throughout Admin.

## 6. Future extension

When adding another client:

1. create/import the Client and its operational data;
2. assign Customer Users to that client or add it to selected Internal Users;
3. validate that product lookup, addresses, carrier configurations, zones and rates are client-owned;
4. create an independent Excel-vs-Django baseline for that client's calculator rules.

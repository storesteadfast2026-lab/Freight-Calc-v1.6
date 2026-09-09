# Multi-client Strategy

STH is the first client, not the only supported client.

Every client-specific table includes `client_id` where needed:

- products
- rates
- zones
- carrier configurations
- tailgate charges
- external files
- calculators
- FROM addresses

New freight calculators should be added by creating a new `Client`, loading that client's data and assigning a `calculation_engine_key`.

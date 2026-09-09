# User Administration Runbook

## Normal location

```text
Django Admin
-> Authentication and Authorization
-> Users
```

Only the native Super User administers Users and Groups.

## Primary access groups

Every normal user must have exactly one:

```text
Administrators
Customers
Steadfast Users
```

Individual User permissions are not available. Configure operational
permissions under:

```text
Django Admin
-> Authentication and Authorization
-> Groups
```

## Administrator

1. Create or open the User.
2. Select `Administrators`.
3. Leave Customer client empty.
4. Save.

The system applies Internal User, All clients, calculator access and
`is_staff=True`. It does not grant User, Group, Permission or superuser
management.

## Customer

1. Create or open the User.
2. Select `Customers`.
3. Select exactly one active Customer client.
4. Save.

The system applies Customer User, Single client, calculator access and
`is_staff=False`.

## Steadfast User

1. Create or open the User.
2. Select `Steadfast Users`.
3. Leave Customer client empty.
4. Save.

The system applies Internal User, All clients, calculator access and
`is_staff=False`. Future quotation permissions require an approved Quotation
specification and model before being assigned to this group.

## Super User

The designated native account is:

```text
super
```

It does not require a primary access group. Its calculator profile is optional.
Create it interactively:

```powershell
docker compose exec -it web python manage.py createsuperuser --username super
```

## Setup command

```powershell
docker compose exec web python manage.py setup_access_roles
```

The command creates or updates the three protected groups. When safe, it
renames the legacy `Django Administrator` group to `Administrators`. It reports
existing individual permissions but does not remove them automatically.

## Troubleshooting order

1. Confirm the User is Active.
2. Confirm exactly one primary group.
3. For Customers, confirm one active client.
4. Read the Effective access summary.
5. Confirm Administrators have Internal User / All clients.
6. Confirm Customers and Steadfast Users are not staff.
7. Review any individual-permission warning from `setup_access_roles`.

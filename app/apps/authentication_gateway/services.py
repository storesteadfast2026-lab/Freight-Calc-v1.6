from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.clients.models import Client

from .models import CalculatorUserProfile


ADMINISTRATORS_GROUP = 'Administrators'
CUSTOMERS_GROUP = 'Customers'
STEADFAST_USERS_GROUP = 'Steadfast Users'
LEGACY_DJANGO_ADMINISTRATOR_GROUP = 'Django Administrator'

# Backwards-compatible import name used by older project code and tests.
DJANGO_ADMINISTRATOR_GROUP = ADMINISTRATORS_GROUP

PRIMARY_ACCESS_GROUPS = (
    ADMINISTRATORS_GROUP,
    CUSTOMERS_GROUP,
    STEADFAST_USERS_GROUP,
)


class CalculatorAccessDenied(PermissionDenied):
    pass


def get_calculator_profile(user) -> CalculatorUserProfile:
    if not user or not user.is_authenticated:
        raise CalculatorAccessDenied('Authentication is required.')
    if not user.is_active:
        raise CalculatorAccessDenied('This user account is inactive.')

    try:
        profile = user.calculator_profile
    except CalculatorUserProfile.DoesNotExist as exc:
        raise CalculatorAccessDenied(
            'This user does not have a calculator access profile.'
        ) from exc

    if not profile.calculator_access:
        raise CalculatorAccessDenied('Calculator access is disabled for this user.')
    return profile


def allowed_clients_for(user):
    profile = get_calculator_profile(user)
    active_clients = Client.objects.filter(active=True).order_by('code')

    if profile.role == CalculatorUserProfile.Role.CUSTOMER_USER:
        if not profile.client_id or not profile.client.active:
            return active_clients.none()
        return active_clients.filter(pk=profile.client_id)

    if profile.role == CalculatorUserProfile.Role.INTERNAL_USER:
        if profile.client_scope == CalculatorUserProfile.ClientScope.ALL_CLIENTS:
            return active_clients
        if profile.client_scope == CalculatorUserProfile.ClientScope.SELECTED_CLIENTS:
            return active_clients.filter(
                authorized_internal_users=profile,
            ).distinct()

    return active_clients.none()


def resolve_authorized_client(user, requested_client_code=None) -> Client:
    profile = get_calculator_profile(user)
    clients = allowed_clients_for(user)
    requested_code = (requested_client_code or '').strip()

    if profile.role == CalculatorUserProfile.Role.CUSTOMER_USER:
        client = clients.first()
        if client is None:
            raise CalculatorAccessDenied('No active client is assigned to this user.')
        if requested_code and requested_code.casefold() != client.code.casefold():
            raise CalculatorAccessDenied('This user cannot access the requested client.')
        return client

    if requested_code:
        client = clients.filter(code__iexact=requested_code).first()
        if client is None:
            raise CalculatorAccessDenied('This user cannot access the requested client.')
        return client

    preferred = clients.filter(code__iexact='STH').first()
    client = preferred or clients.first()
    if client is None:
        raise CalculatorAccessDenied('No active client is available to this user.')
    return client


def is_django_administrator(user) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    if not user.is_staff:
        return False
    if not user.groups.filter(name=ADMINISTRATORS_GROUP).exists():
        return False

    try:
        profile = user.calculator_profile
    except CalculatorUserProfile.DoesNotExist:
        return False

    return (
        profile.calculator_access
        and profile.role == CalculatorUserProfile.Role.INTERNAL_USER
        and profile.client_scope == CalculatorUserProfile.ClientScope.ALL_CLIENTS
        and profile.client_id is None
    )


def primary_access_group_for(user) -> str:
    """Return the user's single protected access group, or an empty string."""
    if not user or not getattr(user, 'pk', None):
        return ''
    names = list(
        user.groups
        .filter(name__in=PRIMARY_ACCESS_GROUPS)
        .values_list('name', flat=True)
    )
    if len(names) > 1:
        raise ValidationError(
            'A user cannot belong to more than one primary access group.'
        )
    return names[0] if names else ''


@transaction.atomic
def configure_user_from_primary_group(user, group_name: str, client=None):
    """Synchronise group, calculator profile and staff status.

    Permissions remain owned by Django Groups. The calculator profile keeps
    client isolation explicit because Django permissions do not carry a client
    scope.
    """
    if user.is_superuser:
        return None

    if group_name not in PRIMARY_ACCESS_GROUPS:
        raise ValidationError('Select one valid primary access group.')

    group = Group.objects.filter(name=group_name).first()
    if group is None:
        raise ValidationError(
            f'Group "{group_name}" does not exist. Run setup_access_roles first.'
        )

    if group_name == CUSTOMERS_GROUP:
        if client is None or not client.active:
            raise ValidationError('Customers require one active client.')
        role = CalculatorUserProfile.Role.CUSTOMER_USER
        scope = CalculatorUserProfile.ClientScope.SINGLE_CLIENT
        profile_client = client
        is_staff = False
    else:
        if client is not None:
            raise ValidationError(
                'Administrators and Steadfast Users must not use a single client.'
            )
        role = CalculatorUserProfile.Role.INTERNAL_USER
        scope = CalculatorUserProfile.ClientScope.ALL_CLIENTS
        profile_client = None
        is_staff = group_name == ADMINISTRATORS_GROUP

    user.groups.remove(
        *Group.objects.filter(name__in=PRIMARY_ACCESS_GROUPS).exclude(pk=group.pk)
    )
    user.groups.add(group)

    if user.is_staff != is_staff:
        user.is_staff = is_staff
        user.save(update_fields=['is_staff'])

    profile, _ = CalculatorUserProfile.objects.get_or_create(
        user=user,
        defaults={
            'role': role,
            'client_scope': scope,
            'client': profile_client,
            'calculator_access': user.is_active,
        },
    )
    profile.role = role
    profile.client_scope = scope
    profile.client = profile_client
    profile.calculator_access = user.is_active
    profile.full_clean()
    profile.save()
    profile.allowed_clients.clear()
    return profile

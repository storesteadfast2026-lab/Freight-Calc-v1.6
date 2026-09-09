from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied

from apps.clients.models import Client

from .models import CalculatorUserProfile


DJANGO_ADMINISTRATOR_GROUP = 'Django Administrator'


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
    if not user.groups.filter(name=DJANGO_ADMINISTRATOR_GROUP).exists():
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

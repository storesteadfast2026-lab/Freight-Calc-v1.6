from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.services import (
    allowed_clients_for,
    get_calculator_profile,
)

from .models import SavedEstimate


def estimates_for_user(user):
    """Return estimates visible to the user without widening client access."""
    queryset = SavedEstimate.objects.select_related('client', 'created_by')

    if user.is_superuser:
        return queryset

    profile = get_calculator_profile(user)
    if profile.role == CalculatorUserProfile.Role.CUSTOMER_USER:
        return queryset.filter(client=profile.client, created_by=user)

    return queryset.filter(client__in=allowed_clients_for(user)).distinct()


def can_export_estimates(user) -> bool:
    if user.is_superuser:
        return True
    profile = get_calculator_profile(user)
    return profile.role == CalculatorUserProfile.Role.INTERNAL_USER


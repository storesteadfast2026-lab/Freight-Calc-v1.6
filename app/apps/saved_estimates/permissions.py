from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.services import (
    allowed_clients_for,
    get_calculator_profile,
)

from .models import SavedEstimate


def estimates_for_user(user):
    """Return only the saved quotations the current user is allowed to see.

    Customer users are isolated to quotations they created for their assigned
    client. Internal users see every quotation for their authorised clients,
    regardless of which customer or internal user created it.
    """
    queryset = SavedEstimate.objects.select_related('client', 'created_by')

    if user.is_superuser:
        return queryset

    profile = get_calculator_profile(user)
    if profile.role == CalculatorUserProfile.Role.CUSTOMER_USER:
        return queryset.filter(client=profile.client, created_by=user)

    if profile.role == CalculatorUserProfile.Role.INTERNAL_USER:
        return queryset.filter(
            client__in=allowed_clients_for(user),
        ).distinct()

    # Defensive default: an unknown role never widens quotation access.
    return queryset.none()


def can_export_estimates(user) -> bool:
    if user.is_superuser:
        return True
    profile = get_calculator_profile(user)
    return profile.role == CalculatorUserProfile.Role.INTERNAL_USER

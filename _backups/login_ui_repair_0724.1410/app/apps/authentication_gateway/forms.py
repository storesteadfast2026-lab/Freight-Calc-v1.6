"""Authentication forms for the calculator login boundary."""

from __future__ import annotations

import logging
from typing import Any

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)

GENERIC_LOGIN_ERROR = (
    "The email/username or password is incorrect. "
    "Your account does not have access to that page."
)


class CalculatorAuthenticationForm(AuthenticationForm):
    """Authenticate credentials and calculator entitlement without leaking account state.

    Every rejected attempt receives the same browser-visible message. The detailed reason is
    written only to the server log using the user primary key where one is available.
    """

    error_messages = {
        "invalid_login": GENERIC_LOGIN_ERROR,
        "inactive": GENERIC_LOGIN_ERROR,
        "unauthorised": GENERIC_LOGIN_ERROR,
    }

    username = forms.CharField(
        label="Email or username",
        widget=forms.TextInput(
            attrs={
                "id": "lp_user",
                "class": "login-input fade-in second",
                "placeholder": "Email or username",
                "autocomplete": "username",
                "autocapitalize": "none",
                "spellcheck": "false",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "id": "lp_password",
                "class": "login-input fade-in third",
                "placeholder": "Password",
                "autocomplete": "current-password",
            }
        ),
    )

    def confirm_login_allowed(self, user: Any) -> None:
        """Reject inactive or non-calculator accounts using one generic response."""
        allowed, reason = self._has_calculator_entitlement(user)
        if allowed:
            return

        logger.warning(
            "Calculator login rejected: user_id=%s reason=%s",
            getattr(user, "pk", None),
            reason,
        )
        raise forms.ValidationError(
            self.error_messages["unauthorised"],
            code="unauthorised",
        )

    @staticmethod
    def _has_calculator_entitlement(user: Any) -> tuple[bool, str]:
        if not getattr(user, "is_active", False):
            return False, "inactive_user"

        try:
            profile = user.calculator_profile
        except (AttributeError, ObjectDoesNotExist):
            return False, "missing_calculator_profile"

        if not getattr(profile, "calculator_access", False):
            return False, "calculator_access_disabled"

        role = str(getattr(profile, "role", ""))
        scope = str(getattr(profile, "client_scope", ""))

        if role == "CUSTOMER_USER":
            client = getattr(profile, "client", None)
            if scope != "SINGLE_CLIENT":
                return False, "invalid_customer_scope"
            if client is None or not getattr(client, "active", False):
                return False, "missing_or_inactive_customer_client"
            return True, "authorised_customer"

        if role == "INTERNAL_USER":
            if scope == "ALL_CLIENTS":
                return True, "authorised_internal_all_clients"
            if scope == "SELECTED_CLIENTS":
                allowed_clients = getattr(profile, "allowed_clients", None)
                if allowed_clients is None:
                    return False, "missing_allowed_clients_relation"
                if allowed_clients.filter(active=True).exists():
                    return True, "authorised_internal_selected_clients"
                return False, "no_active_allowed_clients"
            return False, "invalid_internal_scope"

        return False, "unknown_calculator_role"

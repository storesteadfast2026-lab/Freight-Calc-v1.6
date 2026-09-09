"""Browser authentication views for the freight calculator."""

from __future__ import annotations

from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from .forms import CalculatorAuthenticationForm


class CalculatorLoginView(LoginView):
    """Django session login with a calculator-specific entitlement check."""

    template_name = "registration/login.html"
    authentication_form = CalculatorAuthenticationForm
    redirect_authenticated_user = False

    def get_success_url(self) -> str:
        """Preserve Django's safe `next` handling and default to the calculator."""
        return super().get_success_url()


def permission_denied_view(
    request: HttpRequest,
    exception: Exception | None = None,
) -> HttpResponse:
    """Return generic 403 responses without exposing profile or permission details."""
    del exception
    if request.path.startswith("/api/"):
        return JsonResponse({"error": "Access denied."}, status=403)
    return render(request, "403.html", status=403)

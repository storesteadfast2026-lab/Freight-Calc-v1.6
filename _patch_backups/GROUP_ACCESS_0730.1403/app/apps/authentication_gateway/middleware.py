from django.conf import settings
from django.http import HttpResponseForbidden


class ExternalAuthMiddleware:
    """Compatibility hook for a possible future trusted-proxy integration.

    This middleware does not authenticate users. Version 1 calculator access is
    enforced through Django sessions and CalculatorUserProfile.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header_name = getattr(settings, 'EXTERNAL_AUTH_HEADER', 'HTTP_X_AUTH_USER')
        request.external_auth_user = request.META.get(header_name)
        return self.get_response(request)


class DjangoAdminAccessMiddleware:
    """Reject staff accounts that do not satisfy the approved admin model."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/'):
            user = getattr(request, 'user', None)
            if user and user.is_authenticated and user.is_staff and not user.is_superuser:
                from .services import is_django_administrator

                if not is_django_administrator(user):
                    return HttpResponseForbidden(
                        'Django Admin access requires Internal User / All clients '
                        'and membership in the Django Administrator group.'
                    )
        return self.get_response(request)

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponseForbidden


class ExternalAuthMiddleware:
    """Optional future external-login hook.

    English: When CALCULATOR_REQUIRE_AUTH is disabled, the calculator works without login.
    Español: Cuando CALCULATOR_REQUIRE_AUTH está desactivado, la calculadora funciona sin login.

    English: Later, a reverse proxy or independent auth container can inject a trusted header.
    Español: Más adelante, un proxy o contenedor de autenticación puede inyectar un header confiable.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        require_auth = getattr(settings, 'CALCULATOR_REQUIRE_AUTH', False)
        header_name = getattr(settings, 'EXTERNAL_AUTH_HEADER', 'HTTP_X_AUTH_USER')
        external_user = request.META.get(header_name)
        request.external_auth_user = external_user

        if require_auth and request.path.startswith('/api/') and not external_user and isinstance(request.user, AnonymousUser):
            return HttpResponseForbidden('Authentication required')
        return self.get_response(request)

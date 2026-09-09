from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden, JsonResponse

from .services import CalculatorAccessDenied, get_calculator_profile


def calculator_access_required(view_func):
    """Require an active Django user with an enabled calculator profile."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        is_api = request.path.startswith('/api/')
        if not request.user.is_authenticated:
            if is_api:
                return JsonResponse({'error': 'Authentication required.'}, status=401)
            return redirect_to_login(request.get_full_path())

        try:
            request.calculator_profile = get_calculator_profile(request.user)
        except CalculatorAccessDenied as exc:
            if is_api:
                return JsonResponse({'error': str(exc)}, status=403)
            return HttpResponseForbidden(str(exc))

        return view_func(request, *args, **kwargs)

    return wrapped

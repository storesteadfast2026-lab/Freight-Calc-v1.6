from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse

from .services import CalculatorAccessDenied, get_calculator_profile
from .views import CALCULATOR_ACCESS_MESSAGE


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
        except CalculatorAccessDenied:
            if is_api:
                return JsonResponse(
                    {'error': CALCULATOR_ACCESS_MESSAGE},
                    status=403,
                )

            # logout() flushes the session, so add the message afterwards.
            logout(request)
            messages.error(request, CALCULATOR_ACCESS_MESSAGE)
            return redirect_to_login(request.get_full_path())

        return view_func(request, *args, **kwargs)

    return wrapped

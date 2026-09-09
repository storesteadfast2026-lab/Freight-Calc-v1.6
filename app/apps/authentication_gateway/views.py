from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.csrf import csrf_failure as django_csrf_failure

from .services import CalculatorAccessDenied, get_calculator_profile


CALCULATOR_ACCESS_MESSAGE = (
    'Your account does not have access to the Freight Calculator.'
)
CSRF_SESSION_MESSAGE = (
    'The security token for this page is no longer valid. '
    'Refresh the page and try again.'
)


class CalculatorLoginView(LoginView):
    """Authenticate only users who currently have calculator entitlement."""

    template_name = 'registration/login.html'

    def dispatch(self, request, *args, **kwargs):
        # Clear an old authenticated session when the account no longer has
        # calculator entitlement. Keep the feedback inside the login card.
        if request.user.is_authenticated:
            try:
                get_calculator_profile(request.user)
            except CalculatorAccessDenied:
                logout(request)
                messages.error(request, CALCULATOR_ACCESS_MESSAGE)
            else:
                return HttpResponseRedirect(self.get_success_url())

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # AuthenticationForm already verified the credentials. Check access
        # before Django creates the authenticated session.
        try:
            get_calculator_profile(form.get_user())
        except CalculatorAccessDenied:
            messages.error(self.request, CALCULATOR_ACCESS_MESSAGE)
            return self.form_invalid(form)

        return super().form_valid(form)


def csrf_failure(request, reason=''):
    """Render front-end CSRF failures with the login visual language."""

    if request.path.startswith('/api/'):
        return JsonResponse(
            {'error': 'The request security token is invalid or expired.'},
            status=403,
        )

    if request.path.startswith('/admin/'):
        return django_csrf_failure(request, reason=reason)

    form = AuthenticationForm(request=request)
    return render(
        request,
        'registration/login.html',
        {
            'form': form,
            'next': request.GET.get('next', '/'),
            'login_notice': CSRF_SESSION_MESSAGE,
        },
        status=403,
    )


def permission_denied_view(request, exception=None):
    """Handle global HTTP 403 responses without exposing a plain error page.

    Calculator pages return the approved login screen with an in-card message.
    API endpoints retain a JSON 403 response. Django Admin keeps Django's
    default 403 behaviour.
    """

    from django.contrib import messages
    from django.contrib.auth import logout
    from django.contrib.auth.forms import AuthenticationForm
    from django.http import JsonResponse
    from django.shortcuts import render
    from django.views.defaults import permission_denied as django_permission_denied

    if request.path.startswith('/api/'):
        return JsonResponse(
            {'error': CALCULATOR_ACCESS_MESSAGE},
            status=403,
        )

    if request.path.startswith('/admin/'):
        return django_permission_denied(request, exception)

    if getattr(request, 'user', None) is not None and request.user.is_authenticated:
        logout(request)

    messages.error(request, CALCULATOR_ACCESS_MESSAGE)

    return render(
        request,
        'registration/login.html',
        {
            'form': AuthenticationForm(request=request),
            'next': request.get_full_path(),
        },
        status=403,
    )

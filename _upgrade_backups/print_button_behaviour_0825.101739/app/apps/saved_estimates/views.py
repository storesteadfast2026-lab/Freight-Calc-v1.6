import json

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.authentication_gateway.decorators import calculator_access_required
from apps.authentication_gateway.services import CalculatorAccessDenied

from .permissions import can_export_estimates, estimates_for_user
from .services.calculation_bridge import SnapshotValidationError
from .services.exporters import estimate_csv_response, estimate_xlsx_response
from .services.snapshots import create_verified_estimate


def _require_feature():
    if not getattr(settings, 'SAVED_ESTIMATES_ENABLED', False):
        raise Http404('Saved estimates are disabled.')


def _visible_estimate(user, reference):
    return get_object_or_404(estimates_for_user(user), reference=reference)


@require_GET
@calculator_access_required
def estimate_list(request):
    _require_feature()
    estimates = estimates_for_user(request.user)
    requested_client = request.GET.get('client', '').strip()
    if requested_client:
        estimates = estimates.filter(client__code__iexact=requested_client)
    return render(request, 'saved_estimates/list.html', {
        'estimates': estimates[:200],
        'can_export_estimates': can_export_estimates(request.user),
    })


@require_GET
@calculator_access_required
def estimate_print(request, reference):
    _require_feature()
    estimate = _visible_estimate(request.user, reference)
    return render(request, 'saved_estimates/print.html', {'estimate': estimate})


@require_GET
@calculator_access_required
def estimate_csv(request, reference):
    _require_feature()
    if not can_export_estimates(request.user):
        raise PermissionDenied('Only internal users can export estimates.')
    return estimate_csv_response(_visible_estimate(request.user, reference))


@require_GET
@calculator_access_required
def estimate_xlsx(request, reference):
    _require_feature()
    if not can_export_estimates(request.user):
        raise PermissionDenied('Only internal users can export estimates.')
    return estimate_xlsx_response(_visible_estimate(request.user, reference))


@require_POST
@calculator_access_required
def estimate_save_api(request):
    _require_feature()
    try:
        data = json.loads(request.body.decode('utf-8'))
        estimate = create_verified_estimate(
            request.user,
            data.get('calculation_payload'),
            data.get('displayed_results'),
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON request body.'}, status=400)
    except CalculatorAccessDenied as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    except SnapshotValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=409)

    return JsonResponse({
        'reference': estimate.reference,
        'saved_at': estimate.created_at.isoformat(),
        'print_url': reverse('saved_estimates:print', args=[estimate.reference]),
        'csv_url': reverse('saved_estimates:csv', args=[estimate.reference]),
        'xlsx_url': reverse('saved_estimates:xlsx', args=[estimate.reference]),
        'duplicate_url': reverse(
            'saved_estimates_api:duplicate',
            args=[estimate.reference],
        ),
    }, status=201)


@require_GET
@calculator_access_required
def estimate_duplicate_api(request, reference):
    _require_feature()
    if not can_export_estimates(request.user):
        raise PermissionDenied('Only internal users can duplicate estimates.')
    estimate = _visible_estimate(request.user, reference)
    return JsonResponse({
        'reference': estimate.reference,
        'client_code': estimate.client.code,
        'calculation_payload': estimate.input_snapshot,
    })

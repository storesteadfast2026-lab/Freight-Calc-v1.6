import json
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.authentication_gateway.decorators import calculator_access_required
from apps.authentication_gateway.services import CalculatorAccessDenied

from .permissions import can_export_estimates, estimates_for_user
from .services.calculation_bridge import SnapshotValidationError
from .services.emailing import (
    MAX_ESTIMATES_PER_EMAIL,
    EstimateEmailError,
    estimate_email_is_configured,
    is_customer_user,
    recipient_options_for_client,
    send_estimates_email,
)
from .services.exporters import estimate_csv_response, estimate_xlsx_response
from .services.snapshots import create_verified_estimate


logger = logging.getLogger(__name__)


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
    visible_estimates = estimates[:200]
    clients = {}
    for estimate in visible_estimates:
        clients[estimate.client_id] = estimate.client

    recipient_options = {
        client.code: [
            {'email': option.email, 'label': option.label}
            for option in recipient_options_for_client(request.user, client)
        ]
        for client in clients.values()
    }
    return render(request, 'saved_estimates/list.html', {
        'estimates': visible_estimates,
        'can_export_estimates': can_export_estimates(request.user),
        'estimate_email_enabled': estimate_email_is_configured(),
        'is_customer_user': is_customer_user(request.user),
        'customer_recipient': request.user.email.strip(),
        'recipient_options': recipient_options,
        'max_estimates_per_email': MAX_ESTIMATES_PER_EMAIL,
        'requested_client': requested_client,
    })


@require_POST
@calculator_access_required
def estimate_email(request):
    _require_feature()
    selected_ids = list(dict.fromkeys(request.POST.getlist('estimate_ids')))
    return_client = request.POST.get('return_client', '').strip()

    if not selected_ids:
        messages.error(request, 'Select at least one saved estimate to email.')
        return _redirect_to_estimates(return_client)
    if not all(estimate_id.isdigit() for estimate_id in selected_ids):
        raise PermissionDenied('One or more selected estimates are not available.')
    if len(selected_ids) > MAX_ESTIMATES_PER_EMAIL:
        messages.error(
            request,
            f'Select no more than {MAX_ESTIMATES_PER_EMAIL} estimates per email.',
        )
        return _redirect_to_estimates(return_client)

    visible = estimates_for_user(request.user)
    estimates_by_id = {
        str(estimate.pk): estimate
        for estimate in visible.filter(pk__in=selected_ids).select_related('client')
    }
    if len(estimates_by_id) != len(selected_ids):
        raise PermissionDenied('One or more selected estimates are not available.')
    estimates = [estimates_by_id[estimate_id] for estimate_id in selected_ids]

    client_ids = {estimate.client_id for estimate in estimates}
    if len(client_ids) != 1:
        messages.error(request, 'All selected estimates must belong to one client.')
        return _redirect_to_estimates(return_client)

    try:
        recipient = send_estimates_email(
            sender_user=request.user,
            estimates=estimates,
            recipient=request.POST.get('recipient', ''),
        )
    except EstimateEmailError as exc:
        messages.error(request, str(exc))
    except Exception:
        logger.exception('Saved estimate email delivery failed.')
        messages.error(
            request,
            'The email could not be sent. Please try again or contact an administrator.',
        )
    else:
        count = len(estimates)
        noun = 'estimate' if count == 1 else 'estimates'
        messages.success(
            request,
            f'{count} {noun} emailed successfully to {recipient}.',
        )
    return _redirect_to_estimates(return_client or estimates[0].client.code)


def _redirect_to_estimates(client_code=''):
    target = reverse('saved_estimates:list')
    if client_code:
        target = f'{target}?{urlencode({"client": client_code})}'
    return redirect(target)


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


@require_GET
@calculator_access_required
def estimate_status_api(request):
    """Return the number of estimates visible for the active client."""
    _require_feature()
    client_code = request.GET.get('client', '').strip()
    estimates = estimates_for_user(request.user)
    if client_code:
        estimates = estimates.filter(client__code__iexact=client_code)
    return JsonResponse({'count': estimates.count()})


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
        'visible_count': estimates_for_user(request.user).filter(
            client=estimate.client,
        ).count(),
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

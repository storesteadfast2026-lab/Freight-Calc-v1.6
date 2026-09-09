from decimal import Decimal, InvalidOperation
import json

from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse, HttpRequest
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.authentication_gateway.decorators import calculator_access_required
from apps.authentication_gateway.services import (
    CalculatorAccessDenied,
    allowed_clients_for,
    resolve_authorized_client,
)
from apps.locations.models import Suburb, FromAddress
from apps.products.models import Product

from .services.dtos import FreightRequest, FreightLine
from .services.calculator import FreightCalculatorService
from .services.validators import ValidationError
from .services.consolidator import PALLET_WEIGHT_KG, PALLET_CUBIC_M3
from apps.authentication_gateway.models import CalculatorUserProfile


@ensure_csrf_cookie
@calculator_access_required
def calculator_page(request: HttpRequest):
    try:
        client = resolve_authorized_client(
            request.user,
            request.GET.get('client'),
        )
    except CalculatorAccessDenied as exc:
        raise PermissionDenied(str(exc)) from exc

    available_clients = allowed_clients_for(request.user)
    from_addresses = FromAddress.objects.filter(client=client, active=True)
    profile = request.calculator_profile

    return render(request, 'freight/calculator.html', {
        'client': client,
        'allowed_clients': available_clients,
        'can_select_client': available_clients.count() > 1,
        'user_role_label': profile.get_role_display(),
        'from_addresses': from_addresses,
        'pallet_weight_kg': PALLET_WEIGHT_KG,
        'pallet_cubic_m3': PALLET_CUBIC_M3,
        'saved_estimates_enabled': settings.SAVED_ESTIMATES_ENABLED,
        'can_export_estimates': (
            profile.role == CalculatorUserProfile.Role.INTERNAL_USER
        ),
    })


@require_GET
@calculator_access_required
def suburb_autocomplete(request: HttpRequest):
    q = request.GET.get('q', '').strip()
    qs = Suburb.objects.all()
    if q:
        qs = qs.filter(suburb_name__icontains=q)
    data = [
        {
            'id': s.id,
            'label': f'{s.suburb_name}, {s.state} {s.postcode}',
            'suburb': s.suburb_name,
            'state': s.state,
            'postcode': s.postcode,
        }
        for s in qs[:20]
    ]
    return JsonResponse({'results': data})


@require_GET
@calculator_access_required
def product_autocomplete(request: HttpRequest):
    try:
        client = resolve_authorized_client(request.user, request.GET.get('client'))
    except CalculatorAccessDenied as exc:
        return JsonResponse({'error': str(exc)}, status=403)

    q = request.GET.get('q', '').strip()
    qs = Product.objects.filter(client=client, active=True)
    if q:
        qs = qs.filter(
            Q(sku__icontains=q)
            | Q(name__icontains=q)
            | Q(description__icontains=q)
        )
    data = [
        {
            'sku': p.sku,
            'label': f'{p.sku}',
            'length_m': str(p.length_m),
            'width_m': str(p.width_m),
            'height_m': str(p.height_m),
            'weight_kg': str(p.weight_kg),
            'cubic_m3': str(p.cubic_m3),
            'freight_type': p.freight_type,
        }
        for p in qs.distinct()[:20]
    ]
    return JsonResponse({'results': data})


def _decimal(value, default='0'):
    try:
        return Decimal(str(value if value not in [None, ''] else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


@require_POST
@calculator_access_required
def calculate_freight(request: HttpRequest):
    try:
        payload = json.loads(request.body.decode('utf-8'))
        client = resolve_authorized_client(
            request.user,
            payload.get('client_code'),
        )
        lines = [FreightLine(
            sku=line.get('sku') or None,
            quantity=_decimal(line.get('quantity'), '0'),
            freight_type=line.get('freight_type') or 'P',
            length_m=_decimal(line.get('length_m'), '0'),
            width_m=_decimal(line.get('width_m'), '0'),
            height_m=_decimal(line.get('height_m'), '0'),
            weight_kg=_decimal(line.get('weight_kg'), '0'),
            cubic_m3=_decimal(line.get('cubic_m3'), '0'),
        ) for line in payload.get('lines', [])]
        req = FreightRequest(
            client_code=client.code,
            from_address_id=payload.get('from_address_id'),
            suburb=payload.get('suburb', ''),
            state=payload.get('state', ''),
            postcode=payload.get('postcode'),
            tailgate=str(payload.get('tailgate', 'NO')).upper() == 'YES',
            preselect_sku=str(payload.get('preselect_sku', 'YES')).upper() == 'YES',
            lines=lines,
            cubic_margin_percent=_decimal(payload.get('cubic_margin_percent'), '0'),
        )
        results = FreightCalculatorService().calculate(req)
        return JsonResponse({'results': [r.__dict__ for r in results]})
    except CalculatorAccessDenied as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON request body.'}, status=400)
    except ValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse(
            {'error': 'Unexpected calculation error', 'detail': str(exc)},
            status=500,
        )

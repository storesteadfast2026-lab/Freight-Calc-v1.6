from decimal import Decimal, InvalidOperation
import json
from django.http import JsonResponse, HttpRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from apps.clients.models import Client
from apps.locations.models import Suburb, FromAddress
from apps.products.models import Product
from .services.dtos import FreightRequest, FreightLine
from .services.calculator import FreightCalculatorService
from .services.validators import ValidationError
from .services.consolidator import PALLET_WEIGHT_KG, PALLET_CUBIC_M3
from django.views.decorators.csrf import ensure_csrf_cookie

@ensure_csrf_cookie
def calculator_page(request: HttpRequest):
    client = Client.objects.filter(code='STH').first()
    from_addresses = FromAddress.objects.filter(client=client, active=True) if client else []
    return render(request, 'freight/calculator.html', {
        'client': client,
        'from_addresses': from_addresses,
        'pallet_weight_kg': PALLET_WEIGHT_KG,
        'pallet_cubic_m3': PALLET_CUBIC_M3,
    })


@require_GET
def suburb_autocomplete(request: HttpRequest):
    q = request.GET.get('q', '').strip()
    qs = Suburb.objects.all()
    if q:
        qs = qs.filter(suburb_name__icontains=q)
    data = [{'id': s.id, 'label': f'{s.suburb_name}, {s.state} {s.postcode}', 'suburb': s.suburb_name, 'state': s.state, 'postcode': s.postcode} for s in qs[:20]]
    return JsonResponse({'results': data})


@require_GET
def product_autocomplete(request: HttpRequest):
    client_code = request.GET.get('client', 'STH')
    q = request.GET.get('q', '').strip()
    client = Client.objects.filter(code=client_code).first()
    qs = Product.objects.filter(client=client, active=True) if client else Product.objects.none()
    if q:
        qs = qs.filter(sku__icontains=q) | qs.filter(name__icontains=q) | qs.filter(description__icontains=q)
    data = [
        {'sku': p.sku, 'label': f'{p.sku}', 'length_m': str(p.length_m), 'width_m': str(p.width_m), 'height_m': str(p.height_m), 'weight_kg': str(p.weight_kg), 'cubic_m3': str(p.cubic_m3), 'freight_type': p.freight_type}
        for p in qs.distinct()[:20]
    ]
    return JsonResponse({'results': data})


def _decimal(value, default='0'):
    try:
        return Decimal(str(value if value not in [None, ''] else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


@require_POST
def calculate_freight(request: HttpRequest):
    try:
        payload = json.loads(request.body.decode('utf-8'))
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
            client_code=payload.get('client_code', 'STH'),
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
    except ValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({'error': 'Unexpected calculation error', 'detail': str(exc)}, status=500)

from decimal import Decimal, InvalidOperation

from apps.freight.services.calculator import FreightCalculatorService
from apps.freight.services.dtos import FreightLine, FreightRequest
from apps.locations.models import FromAddress


class SnapshotValidationError(ValueError):
    pass


def _decimal(value, default='0'):
    try:
        return Decimal(str(value if value not in [None, ''] else default))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SnapshotValidationError('The calculation contains an invalid number.') from exc


def build_freight_request(payload, client):
    """Build the existing freight DTO without changing the calculator service."""
    if not isinstance(payload, dict):
        raise SnapshotValidationError('The calculation payload is invalid.')

    lines = []
    for line in payload.get('lines', []):
        if not isinstance(line, dict):
            raise SnapshotValidationError('A freight item is invalid.')
        lines.append(FreightLine(
            sku=line.get('sku') or None,
            quantity=_decimal(line.get('quantity'), '0'),
            freight_type=line.get('freight_type') or 'P',
            length_m=_decimal(line.get('length_m'), '0'),
            width_m=_decimal(line.get('width_m'), '0'),
            height_m=_decimal(line.get('height_m'), '0'),
            weight_kg=_decimal(line.get('weight_kg'), '0'),
            cubic_m3=_decimal(line.get('cubic_m3'), '0'),
        ))

    return FreightRequest(
        client_code=client.code,
        from_address_id=payload.get('from_address_id'),
        suburb=str(payload.get('suburb', '')),
        state=str(payload.get('state', '')),
        postcode=payload.get('postcode'),
        tailgate=str(payload.get('tailgate', 'NO')).upper() == 'YES',
        preselect_sku=str(payload.get('preselect_sku', 'YES')).upper() == 'YES',
        lines=lines,
        cubic_margin_percent=_decimal(payload.get('cubic_margin_percent'), '0'),
    )


def serialise_results(results):
    return [
        {
            'carrier': str(result.carrier),
            'service': str(result.service),
            'estimate_ex_gst': str(result.estimate_ex_gst),
            'status': str(result.status),
            'details': _json_safe(result.details),
        }
        for result in results
    ]


def normalise_displayed_results(results):
    if not isinstance(results, list):
        raise SnapshotValidationError('The displayed freight results are invalid.')
    normalised = []
    for result in results:
        if not isinstance(result, dict):
            raise SnapshotValidationError('A displayed freight result is invalid.')
        normalised.append({
            'carrier': str(result.get('carrier', '')),
            'service': str(result.get('service', '')),
            'estimate_ex_gst': str(result.get('estimate_ex_gst', '')),
            'status': str(result.get('status', '')),
            'details': _json_safe(result.get('details') or {}),
        })
    return normalised


def serialise_request(request_dto, client):
    from_address = None
    if request_dto.from_address_id:
        address = FromAddress.objects.filter(
            pk=request_dto.from_address_id,
            client=client,
        ).first()
        if address:
            from_address = {
                'id': address.id,
                'name': address.name,
                'address_line_1': address.address_line_1,
                'suburb': address.suburb,
                'state': address.state,
                'postcode': address.postcode,
            }

    return {
        'client_code': client.code,
        'from_address_id': request_dto.from_address_id,
        'from_address': from_address,
        'suburb': request_dto.suburb,
        'state': request_dto.state,
        'postcode': request_dto.postcode,
        'tailgate': 'YES' if request_dto.tailgate else 'NO',
        'preselect_sku': 'YES' if request_dto.preselect_sku else 'NO',
        'cubic_margin_percent': str(request_dto.cubic_margin_percent),
        'lines': [
            {
                'sku': line.sku or '',
                'quantity': str(line.quantity),
                'freight_type': line.freight_type,
                'length_m': str(line.length_m),
                'width_m': str(line.width_m),
                'height_m': str(line.height_m),
                'weight_kg': str(line.weight_kg),
                'cubic_m3': str(line.cubic_m3),
            }
            for line in request_dto.lines
        ],
    }


def recalculate_snapshot(payload, client):
    request_dto = build_freight_request(payload, client)
    results = FreightCalculatorService().calculate(request_dto)
    return (
        serialise_request(request_dto, client),
        serialise_results(results),
    )


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


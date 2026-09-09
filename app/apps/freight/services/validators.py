from decimal import Decimal
from .dtos import FreightRequest, ConsolidatedFreight


class ValidationError(Exception):
    pass


def validate_location(request: FreightRequest) -> None:
    """Match CalcLines!D3 / Valida suburb/state/postcode como CalcLines!D3."""
    if not request.suburb or not request.state or not request.postcode or request.postcode == '0000':
        raise ValidationError('Invalid suburb/state/postcode combination')


def validate_consolidated(data: ConsolidatedFreight) -> None:
    """Match CalcLines!D3:L3 / Replica validaciones GOOD/STOP principales."""
    if data.line_count <= 0:
        raise ValidationError('At least one freight line is required')
    if data.weight_total_kg < Decimal('0.01'):
        raise ValidationError('Weight must be >= 0.01 kg')
    if data.cubic_total_m3 < Decimal('0.0001'):
        raise ValidationError('Cubic must be >= 0.0001 m3')
    if data.pallet_count + data.carton_count <= Decimal('0.001'):
        raise ValidationError('At least one pallet or carton is required')
    if data.quantity_total <= Decimal('0.99'):
        raise ValidationError('Quantity must be greater than 0.99')

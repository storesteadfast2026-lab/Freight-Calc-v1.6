from decimal import Decimal
from django.conf import settings
from .dtos import FreightLine, ConsolidatedFreight


def _decimal_setting(name: str, default: str) -> Decimal:
    return Decimal(str(getattr(settings, name, default)))


PALLET_WEIGHT_KG = _decimal_setting('FREIGHT_PALLET_WEIGHT_KG', '32.5')  # CalcLines!J7
PALLET_CUBIC_M3 = _decimal_setting('FREIGHT_PALLET_CUBIC_M3', '0.02')   # CalcLines!K7


def consolidate_lines(lines: list[FreightLine], tailgate: bool) -> ConsolidatedFreight:
    """Consolidate SKU/manual rows like CalcLines rows 12, 24 and 29.

    Excel adds pallet tare weight/cubic when pallet count > 0.99.
    """
    quantity_total = Decimal('0')
    pallet_count = Decimal('0')
    carton_count = Decimal('0')
    product_weight = Decimal('0')
    product_cubic = Decimal('0')
    freight_type_for_rate = ''
    max_length_m = Decimal('0')

    for line in lines:
        quantity_total += line.quantity
        product_weight += line.weight_kg * line.quantity
        product_cubic += line.cubic_m3
        if line.freight_type == 'P':
            pallet_count += line.quantity
        elif line.freight_type == 'C':
            carton_count += line.quantity
        line_largest_dimension = max(
            line.length_m,
            line.width_m,
            line.height_m,
        )
        if line_largest_dimension > max_length_m:
            max_length_m = line_largest_dimension
        if line.length_m > max_length_m:
            max_length_m = line.length_m
        if not freight_type_for_rate and line.freight_type:
            freight_type_for_rate = line.freight_type

    pallet_weight = pallet_count * PALLET_WEIGHT_KG if pallet_count > Decimal('0.99') else Decimal('0')
    pallet_cubic = pallet_count * PALLET_CUBIC_M3 if pallet_count > Decimal('0.99') else Decimal('0')

    return ConsolidatedFreight(
        quantity_total=quantity_total,
        pallet_count=pallet_count,
        carton_count=carton_count,
        weight_total_kg=product_weight + pallet_weight,
        cubic_total_m3=product_cubic + pallet_cubic,
        line_count=len([l for l in lines if l.quantity > 0]),
        tailgate=tailgate if pallet_count > 0 else False,
        freight_type_for_rate='P' if pallet_count > Decimal('0.99') else 'C',
        max_length_m=max_length_m,
    )

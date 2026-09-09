from decimal import Decimal
from apps.rates.models import CarrierTailgateCharge


def calculate_tailgate(client, carrier, pallet_count: Decimal, tailgate: bool) -> Decimal:
    """Replicates SettingFlags tailgate total.

    English: If tailgate is YES, charge max(minimum, per-pallet * pallets).
    Español: Si tailgate es YES, cobra el mayor entre mínimo y cargo por pallet * pallets.
    """
    if not tailgate:
        return Decimal('0')
    try:
        cfg = CarrierTailgateCharge.objects.get(client=client, carrier=carrier)
    except CarrierTailgateCharge.DoesNotExist:
        return Decimal('0')
    variable = cfg.per_subsequent_charge * pallet_count
    return max(cfg.minimum_charge, variable)


def calculate_hand_unload(client, carrier, pallet_count: Decimal, tailgate: bool, enabled: bool) -> Decimal:
    """Excel has a separate Hand Unload path when Tailgate = NO."""
    if tailgate or not enabled or pallet_count <= 0:
        return Decimal('0')
    try:
        cfg = CarrierTailgateCharge.objects.get(client=client, carrier=carrier)
    except CarrierTailgateCharge.DoesNotExist:
        return Decimal('0')
    return cfg.hand_unload_charge * pallet_count

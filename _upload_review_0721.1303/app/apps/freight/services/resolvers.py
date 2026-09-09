from decimal import Decimal
from apps.clients.models import Client
from apps.locations.models import Suburb
from apps.products.models import Product
from apps.rates.models import FreightZone, FreightRate


def resolve_client(code: str) -> Client:
    return Client.objects.get(code=code, active=True)


def resolve_postcode(suburb: str, state: str) -> str:
    """Equivalent to Calculator!E7 STATELOCPOSTLOOKUP."""
    key = f'{state}{suburb}'.upper().strip()
    match = Suburb.objects.filter(normalized_key=key).first()
    return match.postcode if match else '0000'


def resolve_product(client: Client, sku: str) -> Product:
    return Product.objects.get(client=client, sku=sku, active=True)


def resolve_zone(client: Client, carrier_service, suburb: str, state: str, postcode: str | None) -> FreightZone | None:
    """Resolve zone similarly to ZONESUBURB / ZONECARRIER.

    English: Prefer suburb+state because Excel often uses carrier/service + suburb + state.
    Español: Se prioriza suburb+state porque Excel suele usar carrier/service + suburb + state.
    """
    qs = FreightZone.objects.filter(client=client, carrier_service=carrier_service)
    zone = qs.filter(suburb__iexact=suburb, state__iexact=state).first()
    if zone:
        return zone
    if postcode:
        return qs.filter(postcode=str(postcode)).first()
    return None


def resolve_rate(client: Client, carrier_service, zone: FreightZone, customer_code: str, freight_type: str) -> FreightRate | None:
    """Resolve rate by fields, preserving Excel lookup intent."""
    return FreightRate.objects.filter(
        client=client,
        carrier_service=carrier_service,
        zone=zone.zone,
        subzone=zone.subzone,
        area=zone.area,
        customer_code=customer_code,
        freight_type=freight_type,
    ).order_by('weight_break').first()


def decimal_or_zero(value) -> Decimal:
    return Decimal(str(value or '0'))

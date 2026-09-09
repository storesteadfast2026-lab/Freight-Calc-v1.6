from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class FreightLine:
    sku: str | None
    quantity: Decimal
    freight_type: str  # P or C
    length_m: Decimal
    width_m: Decimal
    height_m: Decimal
    weight_kg: Decimal
    cubic_m3: Decimal


@dataclass
class FreightRequest:
    client_code: str
    from_address_id: int | None
    suburb: str
    state: str
    postcode: str | None
    tailgate: bool
    preselect_sku: bool
    lines: list[FreightLine] = field(default_factory=list)


@dataclass
class ConsolidatedFreight:
    quantity_total: Decimal
    pallet_count: Decimal
    carton_count: Decimal
    weight_total_kg: Decimal
    cubic_total_m3: Decimal
    line_count: int
    tailgate: bool
    freight_type_for_rate: str
    max_length_m: Decimal = Decimal('0')


@dataclass
class FreightResult:
    carrier: str
    service: str
    estimate_ex_gst: Decimal
    status: str
    details: dict

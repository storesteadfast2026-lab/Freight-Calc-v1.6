from dataclasses import replace
from decimal import Decimal, ROUND_UP, ROUND_HALF_UP
from apps.carriers.models import ClientCarrierConfig
from apps.rates.models import FreightZone, FreightRate
from .dtos import FreightRequest, FreightResult
from .consolidator import consolidate_lines, PALLET_CUBIC_M3
from .validators import validate_location, validate_consolidated, ValidationError
from .resolvers import resolve_client, resolve_postcode
from .tailgate_calculator import calculate_tailgate, calculate_hand_unload


def roundup(value: Decimal, places: str = '0.01') -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_UP)


def excel_bool(value: bool) -> str:
    return 'YES' if value else 'NO'


def chargeable_weight(cubic_total: Decimal, cubic_conversion: Decimal, actual_weight: Decimal) -> Decimal:
    """BrokerTotals!AF: ROUNDUP(MAX(Cubic*CubicConv, Kg), 0)."""
    volumetric = cubic_total * (cubic_conversion or Decimal('0'))
    return max(volumetric, actual_weight).quantize(Decimal('1'), rounding=ROUND_UP)


MAX_CUBIC_MARGIN_PERCENT = Decimal('20')


def apply_cubic_margin(consolidated, margin_percent: Decimal):
    """Apply optional cubic margin to visible/product cubic before carrier rating.

    The default margin is 0%, so the Excel validation batteries remain unchanged.
    The margin is applied only to product-visible cubic. Pallet cubic is added
    back afterwards because Excel treats pallet cubic as a separate internal
    rating allowance.
    """
    margin_percent = Decimal(str(margin_percent or '0'))

    if margin_percent != margin_percent.to_integral_value():
        raise ValidationError('Cubic margin percent must be a whole number between 0 and 20')
    if margin_percent < Decimal('0') or margin_percent > MAX_CUBIC_MARGIN_PERCENT:
        raise ValidationError('Cubic margin percent must be a whole number between 0 and 20')
    if margin_percent == Decimal('0'):
        return consolidated

    pallet_cubic = (
        consolidated.pallet_count * PALLET_CUBIC_M3
        if consolidated.pallet_count > Decimal('0.99')
        else Decimal('0')
    )
    visible_cubic = consolidated.cubic_total_m3 - pallet_cubic
    adjusted_visible_cubic = (
        visible_cubic * (Decimal('1') + (margin_percent / Decimal('100')))
    ).quantize(Decimal('0.001'), rounding=ROUND_UP)
    adjusted_rating_cubic = (
        adjusted_visible_cubic + pallet_cubic
    ).quantize(Decimal('0.001'), rounding=ROUND_UP)

    return replace(consolidated, cubic_total_m3=adjusted_rating_cubic)


def _teamex_weight_break(weight: Decimal) -> str:
    """BrokerTotals TEAMEX ROAD/GENERAL weight break selector.

    Mirrors the formulas in BrokerTotals rows 13 and 19, columns AJ:AO.
    For example, 2075 kg must resolve to break 3, not break 4.
    """
    if weight < Decimal('751'):
        return '1'
    if weight > Decimal('751.001') and weight < Decimal('1501'):
        return '2'
    if weight > Decimal('1501.001') and weight < Decimal('3001'):
        return '3'
    if weight > Decimal('3001.001') and weight < Decimal('5001'):
        return '4'
    if weight > Decimal('5000.001'):
        return '5'
    return ''


def _tfmx_weight_break(weight: Decimal) -> str:
    """BrokerTotals TFMX ROAD weight break selector.

    Mirrors BrokerTotals row 15, columns AI:AO.
    """
    if weight < Decimal('251'):
        return '1'
    if weight > Decimal('251.001') and weight < Decimal('751'):
        return '2'
    if weight > Decimal('751.001') and weight < Decimal('1501'):
        return '3'
    if weight > Decimal('1501.001') and weight < Decimal('3001'):
        return '4'
    if weight > Decimal('3001.001') and weight < Decimal('5000'):
        return '5'
    if weight > Decimal('5000.001'):
        return '6'
    return ''


def _teamtas_weight_break(weight: Decimal) -> str:
    """BrokerTotals TEAMTAS GENERAL break selector.

    Mirrors BrokerTotals row 20. The workbook assigns break 3
    to both 13-15.99 and 16-17.99 intervals.
    """
    if weight < Decimal('7.99'):
        return '1'
    if weight >= Decimal('8') and weight < Decimal('12.99'):
        return '2'
    if weight >= Decimal('13') and weight < Decimal('15.99'):
        return '3'
    if weight >= Decimal('16') and weight < Decimal('17.99'):
        return '3'
    if weight >= Decimal('18'):
        return '5'
    return ''



def _is_teamtas_general_code(carrier_code: str, service_code: str) -> bool:
    return carrier_code == 'TEAMTAS' and service_code == 'GENERAL'


def _is_teamtas_general_config(cfg: ClientCarrierConfig) -> bool:
    carrier_code = (cfg.carrier_service.carrier.code or '').strip().upper()
    service_code = (cfg.carrier_service.service_code or '').strip().upper()
    return _is_teamtas_general_code(carrier_code, service_code)


def _is_teamtas_general_rate(rate: FreightRate) -> bool:
    carrier_code = (rate.carrier_service.carrier.code or '').strip().upper()
    service_code = (rate.carrier_service.service_code or '').strip().upper()
    return _is_teamtas_general_code(carrier_code, service_code)


def _machipe_mipec_weight_break(weight: Decimal) -> str:
    """BrokerTotals MACHIPE/MIPEC ROAD break selector.

    Mirrors BrokerTotals rows 17 and 21, where break 2 is
    selected only when chargeable weight is greater than 30.
    """
    if weight > Decimal('30'):
        return '2'
    return ''


def excel_weight_break(weight: Decimal) -> str:
    """Legacy generic selector kept for compatibility.

    Do not use this function for carrier rate lookup. Excel does not use a
    single global weight-break rule; BrokerTotals defines carrier-specific
    formulas. Use ``resolve_weight_break_for_config`` instead.
    """
    if weight <= Decimal('251'):
        return '1'
    if weight <= Decimal('751'):
        return '2'
    if weight <= Decimal('1501'):
        return '3'
    if weight <= Decimal('3000'):
        return '4'
    return '5'


def resolve_weight_break_for_config(cfg: ClientCarrierConfig, weight: Decimal) -> str:
    """Resolve BrokerTotals AO WeightBrk using the carrier-specific Excel row.

    The previous implementation applied one generic break function to all
    carriers. That made TEAMEX use break 4 at 2075 kg, while Excel uses
    TEAMEX break 3. This dispatcher prevents TEAMEX logic from leaking into
    TFMX, TEAMTAS, MACHIPE, MIPEC, or carriers with blank WeightBrk.
    """
    carrier_code = (cfg.carrier_service.carrier.code or '').strip().upper()
    service_code = (cfg.carrier_service.service_code or '').strip().upper()

    if carrier_code == 'TEAMEX' and service_code in {'ROAD', 'GENERAL'}:
        return _teamex_weight_break(weight)
    if carrier_code == 'TFMX' and service_code == 'ROAD':
        return _tfmx_weight_break(weight)
    if carrier_code == 'TEAMTAS' and service_code == 'GENERAL':
        return _teamtas_weight_break(weight)
    if carrier_code in {'MACHIPE', 'MIPEC'} and service_code == 'ROAD':
        return _machipe_mipec_weight_break(weight)

    return ''


def overlength_fee(max_length_m: Decimal) -> Decimal:
    """SettingFlags TEAMEXWGTBKTAB approximation.

    Excel uses bracket numbers and a lookup table for overlength.
    """
    if max_length_m < Decimal('2.5'):
        return Decimal('0')
    if max_length_m < Decimal('3.7'):
        return Decimal('60')
    if max_length_m < Decimal('6.0'):
        return Decimal('170')
    if max_length_m <= Decimal('7.2'):
        return Decimal('240')
    return Decimal('850')


class FreightCalculatorService:
    """Main freight engine.

    This version maps the Excel flow more closely:
    Calculator -> CalcLines -> FuelSurcharge -> ZONES -> RATES -> BrokerTotals.
    """

    def calculate(self, request: FreightRequest) -> list[FreightResult]:
        client = resolve_client(request.client_code)
        if not request.postcode:
            request.postcode = resolve_postcode(request.suburb, request.state)
        validate_location(request)
        consolidated = consolidate_lines(request.lines, request.tailgate)
        consolidated = apply_cubic_margin(consolidated, request.cubic_margin_percent)
        validate_consolidated(consolidated)

        results: list[FreightResult] = []
        configs = (
            ClientCarrierConfig.objects
            .select_related('carrier_service__carrier')
            .filter(client=client)
            .order_by('id')
        )

        for cfg in configs:
            diagnostic = self._carrier_status(cfg, request, consolidated)
            if diagnostic != 'L':
                continue

            carrier = cfg.carrier_service.carrier
            carrier_service = cfg.carrier_service
            zone_data = self._resolve_zone_for_config(client, cfg, request)
            if zone_data is None:
                continue

            weight = self._chargeable_weight_for_config(cfg, consolidated)
            rate = self._resolve_rate_for_config(client, cfg, zone_data, consolidated.freight_type_for_rate, weight)
            if rate is None:
                continue

            unit_count = consolidated.pallet_count + consolidated.carton_count
            freight_base = self._calculate_base_freight(rate, weight, unit_count, cfg, consolidated)
            teamtas_general_fee = self._teamtas_general_fee(cfg, consolidated)
            tailgate_fee = calculate_tailgate(client, carrier, consolidated.pallet_count, consolidated.tailgate) if cfg.tailgate_enabled else Decimal('0')
            hand_unload = calculate_hand_unload(client, carrier, consolidated.pallet_count, consolidated.tailgate, cfg.hand_unload_enabled)
            overlength = overlength_fee(consolidated.max_length_m) if cfg.overlength_enabled else Decimal('0')
            handling = cfg.fixed_handling_charge if cfg.warehouse_handling_enabled else Decimal('0')
            fuel = freight_base * (cfg.fuel_levy + cfg.extra_surcharge)

            subtotal_before_uprate = (
                freight_base
                + rate.overweight_charge
                + overlength
                + tailgate_fee
                + hand_unload
                + rate.remote_charge
                + rate.offshore_charge
                + teamtas_general_fee
                + fuel
            )
            uprate_amount = subtotal_before_uprate * cfg.uprate
            total_before_display = subtotal_before_uprate + uprate_amount + handling
            estimate = self._final_estimate_for_config(cfg, total_before_display)

            results.append(FreightResult(
                carrier=carrier.code,
                service=carrier_service.service_code,
                estimate_ex_gst=estimate,
                status='L',
                details={
                    'zone': zone_data['zone'],
                    'subzone': zone_data['subzone'],
                    'area': zone_data['area'],
                    'rate_lookup_key': rate.lookup_key,
                    'rate_source_row': rate.source_row,
                    'chargeable_weight': str(weight),
                    'actual_weight': str(consolidated.weight_total_kg),
                    'cubic_total': str(consolidated.cubic_total_m3),
                    'pallets': str(consolidated.pallet_count),
                    'cartons': str(consolidated.carton_count),
                    'freight_type': consolidated.freight_type_for_rate,
                    'freight_base': str(freight_base),
                    'fuel': str(roundup(fuel)),
                    'tailgate_fee': str(roundup(tailgate_fee)),
                    'hand_unload': str(roundup(hand_unload)),
                    'overlength': str(roundup(overlength)),
                    'teamtas_general_fee': str(teamtas_general_fee),
                    'remote': str(rate.remote_charge),
                    'offshore': str(rate.offshore_charge),
                    'handling': str(handling),
                    'mapping': 'Excel-like BrokerTotals calculation from imported FuelSurcharge/ZONES/RATES rows.',
                }
            ))
        return sorted(results, key=lambda r: r.estimate_ex_gst)

    def _carrier_status(self, cfg: ClientCarrierConfig, request: FreightRequest, consolidated) -> str:
        """Replicate FuelSurcharge!AA status behaviour.

        L is contextual, not a fixed carrier flag.
        """
        if cfg.base_status != 'L' or not cfg.active:
            return 'X'
        if consolidated.tailgate and not cfg.tailgate_enabled:
            return 'X'
        if cfg.order_ready_rule == 'WOODVILLE_NORTH_ONLY' and request.suburb.strip().upper() != 'WOODVILLE NORTH':
            return 'X'
        if consolidated.pallet_count > Decimal('0.99') and cfg.pallet_enabled:
            return 'L'
        if consolidated.carton_count > Decimal('0.99') and cfg.carton_enabled:
            return 'L'
        return 'X'

    def _resolve_zone_for_config(self, client, cfg: ClientCarrierConfig, request: FreightRequest) -> dict | None:
        """Replicate BrokerTotals zone/subzone/area lookup intent."""
        zone = ''
        subzone = ''
        area = ''

        if cfg.zone_enabled:
            qs = FreightZone.objects.filter(client=client, carrier_service=cfg.carrier_service)

            # Excel-style zone resolution:
            # 1) Prefer exact Suburb + State. This avoids using the first postcode row
            #    when many suburbs share the same postcode.
            # 2) For TEAMEX, do not fall back to postcode-only aliases. Excel did not
            #    rate TEAMEX for cases where only a postcode alias matched.
            match = qs.filter(
                suburb__iexact=request.suburb,
                state__iexact=request.state,
            ).order_by('source_row').first()

            carrier_code = (cfg.carrier_service.carrier.code or '').strip().upper()
            allow_postcode_fallback = cfg.postcode_zones_enabled and carrier_code not in {'TEAMEX'}

            if match is None and allow_postcode_fallback and request.postcode:
                match = qs.filter(postcode=str(request.postcode)).order_by('source_row').first()

            if match is None:
                return None
            zone = match.zone or ''
            subzone = match.subzone or '' if cfg.subzone_enabled else ''
            area = match.area or '' if cfg.area_enabled else ''

        return {'zone': zone, 'subzone': subzone, 'area': area}

    def _resolve_rate_for_config(self, client, cfg: ClientCarrierConfig, zone_data: dict, freight_type: str, weight: Decimal) -> FreightRate | None:
        wb = resolve_weight_break_for_config(cfg, weight)
        base_qs = FreightRate.objects.filter(
            client=client,
            carrier_service=cfg.carrier_service,
            zone=zone_data['zone'],
            subzone=zone_data['subzone'],
            area=zone_data['area'],
            customer_code=cfg.customer_code,
            freight_type=freight_type,
        )
        # Excel key includes AO WeightBreak; blank is valid for most carriers.
        rate = base_qs.filter(weight_break=wb).first()
        if rate:
            return rate
        rate = base_qs.filter(weight_break='').first()
        if rate:
            return rate
        # Safety fallback for tables where subzone/area data exists but config suppresses it.
        return FreightRate.objects.filter(
            client=client,
            carrier_service=cfg.carrier_service,
            zone=zone_data['zone'],
            customer_code=cfg.customer_code,
            freight_type=freight_type,
        ).filter(weight_break__in=[wb, '']).order_by('-weight_break').first()

    def _chargeable_weight_for_config(self, cfg: ClientCarrierConfig, consolidated) -> Decimal:
        """Return BrokerTotals!AF value for the carrier row.

        TEAMTAS GENERAL is charged in whole tonnes/cubic units. Excel row 20
        compares rating cubic (CalcLines!P29 * cubic conversion) with actual
        weight in tonnes (CalcLines!O29 / 1000), then rounds up to a whole unit.
        Other carriers keep the previous kg-based chargeable weight logic.
        """
        if _is_teamtas_general_config(cfg):
            rating_units = consolidated.cubic_total_m3 * (cfg.cubic_conversion or Decimal('0'))
            actual_tonnes = consolidated.weight_total_kg / Decimal('1000')
            return max(rating_units, actual_tonnes).quantize(Decimal('1'), rounding=ROUND_UP)
        return chargeable_weight(consolidated.cubic_total_m3, cfg.cubic_conversion, consolidated.weight_total_kg)

    def _calculate_base_freight(self, rate: FreightRate, weight: Decimal, unit_count: Decimal, cfg: ClientCarrierConfig, consolidated) -> Decimal:
        """Replicate BrokerTotals!L main formula.

        Most carriers use Basic + Subsequent + Rate*ChargeableWeight.
        TEAMTAS GENERAL row 20 is different: Excel multiplies Basic by rating
        cubic units before adding Rate*whole-tonne chargeable weight.
        """
        subsequent = Decimal('0')
        if unit_count > Decimal('1.99'):
            subsequent = (unit_count - Decimal('1')) * rate.per_subsequent_basic

        if _is_teamtas_general_rate(rate):
            rating_units = consolidated.cubic_total_m3 * (cfg.cubic_conversion or Decimal('0'))
            candidate = (rate.basic_charge * rating_units) + subsequent + (rate.per_kg * weight)
        else:
            candidate = rate.basic_charge + subsequent + (rate.per_kg * weight)

        base = max(rate.minimum_charge, candidate)
        return roundup(base)

    def _teamtas_general_fee(self, cfg: ClientCarrierConfig, consolidated) -> Decimal:
        """Replicate BrokerTotals!AW20 for TEAMTAS GENERAL.

        Excel row 20 adds AW20 outside the freight base:
        AW20 = (CalcLines!M29 * 2) + (CalcLines!L29 * 0.6)
        where M29 is pallet count and L29 is Calculator-visible cubic. Django's
        consolidated cubic includes pallet cubic, so remove pallet cubic first.
        """
        if not _is_teamtas_general_config(cfg):
            return Decimal('0')
        visible_cubic = consolidated.cubic_total_m3 - (consolidated.pallet_count * PALLET_CUBIC_M3)
        return (consolidated.pallet_count * Decimal('2')) + (visible_cubic * Decimal('0.6'))

    def _final_estimate_for_config(self, cfg: ClientCarrierConfig, total: Decimal) -> Decimal:
        """Return the amount as Excel displays it for the carrier row."""
        if _is_teamtas_general_config(cfg):
            return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return roundup(total)

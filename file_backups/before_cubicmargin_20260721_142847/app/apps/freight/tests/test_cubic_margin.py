from decimal import Decimal

from apps.freight.services.validators import ValidationError
from django.test import SimpleTestCase

from apps.freight.services.calculator import apply_cubic_margin
from apps.freight.services.dtos import ConsolidatedFreight


class CubicMarginTests(SimpleTestCase):
    def _consolidated(self, *, cubic='4.040', pallets='2'):
        return ConsolidatedFreight(
            quantity_total=Decimal('2'),
            pallet_count=Decimal(pallets),
            carton_count=Decimal('0'),
            weight_total_kg=Decimal('865'),
            cubic_total_m3=Decimal(cubic),
            line_count=2,
            tailgate=False,
            freight_type_for_rate='P',
            max_length_m=Decimal('1.2'),
        )

    def test_zero_margin_preserves_original_consolidation(self):
        original = self._consolidated()
        self.assertIs(apply_cubic_margin(original, Decimal('0')), original)

    def test_margin_applies_to_visible_cubic_then_adds_pallet_cubic(self):
        # 4.040 rating cubic contains 4.000 visible cubic + 0.040 pallet allowance.
        result = apply_cubic_margin(self._consolidated(), Decimal('10'))
        self.assertEqual(result.cubic_total_m3, Decimal('4.440'))

    def test_twenty_percent_is_allowed(self):
        result = apply_cubic_margin(self._consolidated(), Decimal('20'))
        self.assertEqual(result.cubic_total_m3, Decimal('4.840'))

    def test_margin_rounds_visible_cubic_up_to_three_decimals(self):
        result = apply_cubic_margin(
            self._consolidated(cubic='1.254', pallets='0'),
            Decimal('1'),
        )
        self.assertEqual(result.cubic_total_m3, Decimal('1.267'))

    def test_negative_margin_is_rejected(self):
        with self.assertRaises(ValidationError):
            apply_cubic_margin(self._consolidated(), Decimal('-1'))

    def test_margin_above_twenty_is_rejected(self):
        with self.assertRaises(ValidationError):
            apply_cubic_margin(self._consolidated(), Decimal('21'))

    def test_decimal_margin_is_rejected(self):
        with self.assertRaises(ValidationError):
            apply_cubic_margin(self._consolidated(), Decimal('10.5'))

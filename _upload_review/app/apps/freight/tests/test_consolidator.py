from decimal import Decimal
from django.test import SimpleTestCase
from apps.freight.services.dtos import FreightLine
from apps.freight.services.consolidator import consolidate_lines


class ConsolidatorTests(SimpleTestCase):
    def test_pallet_weight_and_cubic_are_added(self):
        lines = [
            FreightLine('A', Decimal('1'), 'P', Decimal('1.2'), Decimal('0.8'), Decimal('0.35'), Decimal('70'), Decimal('0.336')),
            FreightLine('B', Decimal('1'), 'P', Decimal('0.91'), Decimal('0.62'), Decimal('0.49'), Decimal('113'), Decimal('0.276')),
        ]
        result = consolidate_lines(lines, tailgate=True)
        self.assertEqual(result.pallet_count, Decimal('2'))
        self.assertEqual(result.weight_total_kg, Decimal('248.0'))
        self.assertEqual(result.cubic_total_m3, Decimal('0.652'))

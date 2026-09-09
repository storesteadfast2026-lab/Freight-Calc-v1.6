from decimal import Decimal
from django.test import TestCase
from apps.clients.models import Client
from apps.carriers.models import Carrier
from apps.rates.models import CarrierTailgateCharge
from apps.freight.services.tailgate_calculator import calculate_tailgate


class TailgateTests(TestCase):
    def test_tailgate_uses_max_minimum_or_per_pallet(self):
        client = Client.objects.create(code='STH', name='Stenhoj')
        carrier = Carrier.objects.create(code='KTI')
        CarrierTailgateCharge.objects.create(client=client, carrier=carrier, minimum_charge=Decimal('37'), per_subsequent_charge=Decimal('37'))
        self.assertEqual(calculate_tailgate(client, carrier, Decimal('1'), True), Decimal('37'))
        self.assertEqual(calculate_tailgate(client, carrier, Decimal('3'), True), Decimal('111'))
        self.assertEqual(calculate_tailgate(client, carrier, Decimal('3'), False), Decimal('0'))

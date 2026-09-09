from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.clients.models import Client
from apps.locations.models import Suburb


class CalculatorVisualContractTests(TestCase):
    """Protect the existing calculator contract during visual-only changes."""

    def setUp(self):
        self.client_record = Client.objects.create(code='STH', name='Steadfast')
        self.user = get_user_model().objects.create_user(
            username='customer@example.com',
            email='customer@example.com',
            password='test-pass',
        )
        CalculatorUserProfile.objects.create(
            user=self.user,
            role=CalculatorUserProfile.Role.CUSTOMER_USER,
            client_scope=CalculatorUserProfile.ClientScope.SINGLE_CLIENT,
            client=self.client_record,
        )
        self.client.force_login(self.user)

    def test_visual_layout_keeps_existing_dom_contract(self):
        response = self.client.get(reverse('freight_calculator'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="calculator-page"')
        self.assertContains(response, 'class="fc-workspace"')
        self.assertContains(response, 'Shipment summary')

        required_ids = (
            'from_address_id',
            'suburb_search',
            'suburb_results',
            'destination_suburb',
            'state',
            'postcode',
            'tailgate',
            'preselect_sku',
            'cubic_margin_percent',
            'lines',
            'item_count',
            'total_weight',
            'total_cubic',
            'calc_status',
            'error',
            'results',
        )
        for element_id in required_ids:
            self.assertContains(response, f'id="{element_id}"', count=1)

    def test_destination_uses_one_visible_selector_and_hidden_components(self):
        response = self.client.get(reverse('freight_calculator'))

        self.assertContains(response, '<span class="field-label">To Suburb</span>')
        self.assertContains(response, '<input id="destination_suburb" type="hidden">')
        self.assertContains(response, '<input id="state" type="hidden">')
        self.assertContains(response, '<input id="postcode" type="hidden">')
        self.assertNotContains(response, '<span class="field-label">State</span>')
        self.assertNotContains(response, '<span class="field-label">Postcode</span>')
        self.assertContains(response, 'suburb:destinationSuburbInput.value')
        self.assertContains(response, 'state:destinationStateInput.value')
        self.assertContains(response, 'postcode:destinationPostcodeInput.value')

    def test_suburb_autocomplete_returns_full_label_and_separate_values(self):
        Suburb.objects.create(
            suburb_name='ADELAIDE',
            state='SA',
            postcode='5000',
        )

        response = self.client.get(reverse('suburb_autocomplete'), {'q': 'Adelaide'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'], [{
            'id': Suburb.objects.get().id,
            'label': 'ADELAIDE, SA 5000',
            'suburb': 'ADELAIDE',
            'state': 'SA',
            'postcode': '5000',
        }])

    def test_visual_layout_keeps_current_actions_without_unimplemented_controls(self):
        response = self.client.get(reverse('freight_calculator'))

        self.assertContains(response, 'onclick="addLine()"')
        self.assertContains(response, 'onclick="calculate()"')
        self.assertContains(response, "fetch('/api/calculate/'")
        self.assertNotContains(response, 'Save this shipment')
        self.assertNotContains(response, 'Where it&#x27;s going')
        self.assertNotContains(response, 'View and choose')

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.clients.models import Client


class FreightUserAccessTests(TestCase):
    def setUp(self):
        self.sth = Client.objects.create(code='STH', name='STH')
        self.other = Client.objects.create(code='OTHER', name='Other')
        self.User = get_user_model()

    def _customer(self):
        user = self.User.objects.create_user(
            username='customer@example.com',
            email='customer@example.com',
            password='test-pass',
        )
        CalculatorUserProfile.objects.create(
            user=user,
            role=CalculatorUserProfile.Role.CUSTOMER_USER,
            client_scope=CalculatorUserProfile.ClientScope.SINGLE_CLIENT,
            client=self.sth,
        )
        return user

    def _internal_selected(self):
        user = self.User.objects.create_user(
            username='internal@example.com',
            email='internal@example.com',
            password='test-pass',
        )
        profile = CalculatorUserProfile.objects.create(
            user=user,
            role=CalculatorUserProfile.Role.INTERNAL_USER,
            client_scope=CalculatorUserProfile.ClientScope.SELECTED_CLIENTS,
        )
        profile.allowed_clients.add(self.other)
        return user

    def test_anonymous_page_redirects_to_login(self):
        response = self.client.get(reverse('freight_calculator'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_anonymous_api_returns_json_401(self):
        response = self.client.get(reverse('product_autocomplete'))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'Authentication required.')

    def test_customer_page_uses_assigned_client(self):
        self.client.force_login(self._customer())
        response = self.client.get(reverse('freight_calculator'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['client'], self.sth)

    def test_customer_cannot_switch_client_in_query_string(self):
        self.client.force_login(self._customer())
        response = self.client.get(reverse('freight_calculator'), {'client': 'OTHER'})
        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_query_products_for_other_client(self):
        self.client.force_login(self._customer())
        response = self.client.get(reverse('product_autocomplete'), {'client': 'OTHER'})
        self.assertEqual(response.status_code, 403)

    @patch('apps.freight.views.FreightCalculatorService.calculate', return_value=[])
    def test_calculation_uses_server_authorized_client(self, mocked_calculate):
        self.client.force_login(self._customer())
        payload = {
            'client_code': 'STH',
            'suburb': 'Adelaide',
            'state': 'SA',
            'postcode': '5000',
            'lines': [],
        }
        response = self.client.post(
            reverse('calculate_freight'),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        request_dto = mocked_calculate.call_args.args[0]
        self.assertEqual(request_dto.client_code, 'STH')

    def test_calculation_rejects_tampered_client(self):
        self.client.force_login(self._customer())
        response = self.client.post(
            reverse('calculate_freight'),
            data=json.dumps({'client_code': 'OTHER', 'lines': []}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_internal_user_can_use_selected_client(self):
        self.client.force_login(self._internal_selected())
        response = self.client.get(reverse('freight_calculator'), {'client': 'OTHER'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['client'], self.other)

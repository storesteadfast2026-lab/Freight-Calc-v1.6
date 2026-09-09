import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.clients.models import Client
from apps.freight.services.dtos import FreightResult

from ..models import SavedEstimate


def freight_result(amount='123.45'):
    return FreightResult(
        carrier='KTI',
        service='ROAD',
        estimate_ex_gst=Decimal(amount),
        status='L',
        details={
            'actual_weight': '100.000',
            'cubic_total': '1.250',
            'fuel': '10.00',
            'tailgate_fee': '0.00',
        },
    )


def displayed_result(amount='123.45'):
    result = freight_result(amount)
    return {
        'carrier': result.carrier,
        'service': result.service,
        'estimate_ex_gst': str(result.estimate_ex_gst),
        'status': result.status,
        'details': result.details,
    }


class SavedEstimateTests(TestCase):
    def setUp(self):
        self.sth = Client.objects.create(code='STH', name='Stenhoj Australia')
        self.other = Client.objects.create(code='OTHER', name='Other Client')
        self.User = get_user_model()
        self.customer = self._customer('customer@example.com', self.sth)
        self.other_customer = self._customer('other@example.com', self.sth)
        self.internal = self._internal('internal@example.com', self.sth)
        self.payload = {
            'client_code': 'STH',
            'from_address_id': None,
            'suburb': 'ADELAIDE',
            'state': 'SA',
            'postcode': '5000',
            'tailgate': 'NO',
            'preselect_sku': 'YES',
            'cubic_margin_percent': 0,
            'lines': [{
                'sku': 'SKU-1',
                'quantity': '1',
                'freight_type': 'P',
                'length_m': '1.00',
                'width_m': '1.00',
                'height_m': '1.00',
                'weight_kg': '67.50',
                'cubic_m3': '1.230',
            }],
        }

    def _customer(self, username, client):
        user = self.User.objects.create_user(
            username=username,
            email=username,
            password='test-pass',
        )
        CalculatorUserProfile.objects.create(
            user=user,
            role=CalculatorUserProfile.Role.CUSTOMER_USER,
            client_scope=CalculatorUserProfile.ClientScope.SINGLE_CLIENT,
            client=client,
        )
        return user

    def _internal(self, username, client):
        user = self.User.objects.create_user(
            username=username,
            email=username,
            password='test-pass',
        )
        profile = CalculatorUserProfile.objects.create(
            user=user,
            role=CalculatorUserProfile.Role.INTERNAL_USER,
            client_scope=CalculatorUserProfile.ClientScope.SELECTED_CLIENTS,
        )
        profile.allowed_clients.add(client)
        return user

    def _save(self, user=None, displayed=None):
        self.client.force_login(user or self.customer)
        with patch(
            'apps.saved_estimates.services.calculation_bridge.'
            'FreightCalculatorService.calculate',
            return_value=[freight_result()],
        ):
            return self.client.post(
                reverse('saved_estimates_api:save'),
                data=json.dumps({
                    'calculation_payload': self.payload,
                    'displayed_results': displayed or [displayed_result()],
                }),
                content_type='application/json',
            )

    def test_save_recalculates_with_existing_engine_and_stores_snapshot(self):
        response = self._save()

        self.assertEqual(response.status_code, 201)
        estimate = SavedEstimate.objects.get()
        self.assertRegex(estimate.reference, r'^EST-\d{8}-\d{6}$')
        self.assertEqual(estimate.client, self.sth)
        self.assertEqual(estimate.created_by, self.customer)
        self.assertEqual(estimate.destination_label, 'ADELAIDE, SA 5000')
        self.assertEqual(estimate.best_estimate_ex_gst, Decimal('123.45'))
        self.assertEqual(estimate.result_snapshot, [displayed_result()])

    def test_save_rejects_browser_result_that_does_not_match_engine(self):
        response = self._save(displayed=[displayed_result('999.99')])

        self.assertEqual(response.status_code, 409)
        self.assertEqual(SavedEstimate.objects.count(), 0)

    def test_customer_history_contains_only_estimates_created_by_customer(self):
        first = self._save().json()['reference']
        self._save(user=self.other_customer)
        self.client.force_login(self.customer)

        response = self.client.get(reverse('saved_estimates:list'))

        self.assertContains(response, first)
        self.assertEqual(response.context['estimates'].count(), 1)

    def test_internal_user_can_view_authorised_client_estimates(self):
        reference = self._save().json()['reference']
        self.client.force_login(self.internal)

        response = self.client.get(reverse('saved_estimates:list'))

        self.assertContains(response, reference)

    def test_customer_cannot_export_tabular_files(self):
        reference = self._save().json()['reference']

        response = self.client.get(
            reverse('saved_estimates:csv', args=[reference])
        )

        self.assertEqual(response.status_code, 403)

    def test_internal_user_can_export_csv_and_excel(self):
        reference = self._save().json()['reference']
        self.client.force_login(self.internal)

        csv_response = self.client.get(
            reverse('saved_estimates:csv', args=[reference])
        )
        xlsx_response = self.client.get(
            reverse('saved_estimates:xlsx', args=[reference])
        )

        self.assertEqual(csv_response.status_code, 200)
        self.assertIn(b'KTI,ROAD,123.45,L', csv_response.content)
        self.assertEqual(xlsx_response.status_code, 200)
        self.assertEqual(
            xlsx_response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )


    @override_settings(
        ESTIMATE_EMAIL_ENABLED=True,
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST='smtp.example.com',
        EMAIL_PORT=587,
        EMAIL_HOST_USER='sender@example.com',
        EMAIL_HOST_PASSWORD='secret',
        DEFAULT_FROM_EMAIL='sender@example.com',
    )
    def test_email_sends_pdf_attachment_and_keeps_quote_details_out_of_body(self):
        self._save()
        estimate = SavedEstimate.objects.get()
        self.client.force_login(self.internal)

        response = self.client.post(
            reverse('saved_estimates:email'),
            data={
                'estimate_ids': [str(estimate.pk)],
                'recipient': self.customer.email,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn('Please find attached the requested freight quotation.', message.body)
        self.assertNotIn('Available freight options', message.body)
        self.assertNotIn('KTI', message.body)
        self.assertNotIn('123.45', message.body)
        self.assertEqual(len(message.attachments), 1)
        filename, content, mimetype = message.attachments[0]
        self.assertEqual(filename, f'{estimate.reference}.pdf')
        self.assertEqual(mimetype, 'application/pdf')
        self.assertTrue(content.startswith(b'%PDF'))

    @override_settings(
        ESTIMATE_EMAIL_ENABLED=True,
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST='smtp.example.com',
        EMAIL_PORT=587,
        EMAIL_HOST_USER='sender@example.com',
        EMAIL_HOST_PASSWORD='secret',
        DEFAULT_FROM_EMAIL='sender@example.com',
    )
    def test_email_attaches_one_pdf_per_selected_estimate(self):
        self._save()
        self._save()
        estimates = list(SavedEstimate.objects.order_by('pk'))
        self.client.force_login(self.internal)

        response = self.client.post(
            reverse('saved_estimates:email'),
            data={
                'estimate_ids': [str(estimate.pk) for estimate in estimates],
                'recipient': self.customer.email,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].attachments), 2)
        self.assertEqual(
            {attachment[0] for attachment in mail.outbox[0].attachments},
            {f'{estimate.reference}.pdf' for estimate in estimates},
        )

    def test_duplicate_api_returns_saved_input_without_recalculating(self):
        reference = self._save().json()['reference']
        self.client.force_login(self.internal)

        response = self.client.get(
            reverse('saved_estimates_api:duplicate', args=[reference])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['calculation_payload']['suburb'], 'ADELAIDE')

    def test_customer_cannot_duplicate_estimates(self):
        reference = self._save().json()['reference']

        response = self.client.get(
            reverse('saved_estimates_api:duplicate', args=[reference])
        )

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_open_another_customers_estimate(self):
        reference = self._save(user=self.other_customer).json()['reference']
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse('saved_estimates:print', args=[reference])
        )

        self.assertEqual(response.status_code, 404)

    @override_settings(SAVED_ESTIMATES_ENABLED=False)
    def test_feature_flag_hides_buttons_and_blocks_saved_estimate_pages(self):
        self.client.force_login(self.customer)

        calculator = self.client.get(reverse('freight_calculator'))
        history = self.client.get(reverse('saved_estimates:list'))

        self.assertNotContains(calculator, 'id="estimate_actions"')
        self.assertEqual(history.status_code, 404)

    def test_calculator_keeps_existing_api_and_adds_only_result_event_hook(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('freight_calculator'))

        self.assertContains(response, "fetch('/api/calculate/'")
        self.assertContains(response, "new CustomEvent('freight:calculated'")
        self.assertContains(response, 'id="estimate_actions"')

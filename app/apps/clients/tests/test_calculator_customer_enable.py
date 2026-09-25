from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.clients.admin import EnableCalculatorCustomerForm
from apps.clients.calculator_customer_enable import (
    CalculatorCustomerConflict, enable_calculator_customer,
)
from apps.clients.models import Client, Customer
from apps.products.models import Product


class CalculatorCustomerEnableTests(TestCase):
    def setUp(self):
        self.pon = Customer.objects.create(code='PON', name='Pon Bike', source_row_number=2)
        self.special = Customer.objects.create(
            code='*', name='All Customers', is_special=True, source_row_number=3,
        )

    def test_new_customer_creates_client_and_links_once(self):
        client, created = enable_calculator_customer(self.pon.pk)
        self.assertTrue(created)
        self.assertEqual((client.code, client.name, client.active), ('PON', 'Pon Bike', True))
        self.pon.refresh_from_db()
        self.assertEqual(self.pon.linked_client, client)
        again, created = enable_calculator_customer(self.pon.pk)
        self.assertFalse(created)
        self.assertEqual((again.pk, Client.objects.count()), (client.pk, 1))

    def test_special_customer_blocked_even_if_flag_was_cleared(self):
        for is_special in (True, False):
            Customer.objects.filter(pk=self.special.pk).update(is_special=is_special)
            with self.assertRaises(CalculatorCustomerConflict):
                enable_calculator_customer(self.special.pk)
        self.assertFalse(Client.objects.exists())

    def test_existing_free_client_is_linked_without_replacing_name(self):
        existing = Client.objects.create(code='PON', name='Existing operational name', active=False)
        linked, created = enable_calculator_customer(self.pon.pk, active=True)
        existing.refresh_from_db()
        self.pon.refresh_from_db()
        self.assertEqual((linked.pk, created), (existing.pk, False))
        self.assertEqual(existing.name, 'Existing operational name')
        self.assertTrue(existing.active)
        self.assertEqual(self.pon.linked_client, existing)

    def test_existing_client_linked_elsewhere_is_a_conflict_and_does_not_change(self):
        existing = Client.objects.create(code='PON', name='Original', active=False)
        owner = Customer.objects.create(
            code='OTHER', name='Original owner', linked_client=existing, source_row_number=4,
        )
        with self.assertRaisesRegex(CalculatorCustomerConflict, 'already linked'):
            enable_calculator_customer(self.pon.pk, active=True)
        existing.refresh_from_db()
        self.pon.refresh_from_db()
        self.assertFalse(existing.active)
        self.assertIsNone(self.pon.linked_client)
        self.assertEqual(owner.linked_client_id, existing.pk)
        self.assertEqual(Client.objects.count(), 1)

    def test_dropdown_excludes_linked_and_special_customers(self):
        other = Customer.objects.create(code='STH', name='STH', source_row_number=4)
        client = Client.objects.create(code='STH', name='STH')
        other.linked_client = client
        other.save(update_fields=['linked_client'])
        self.assertEqual(list(EnableCalculatorCustomerForm().fields['customer'].queryset), [self.pon])

    def test_product_remains_under_original_client(self):
        existing = Client.objects.create(code='PON', name='Original')
        product = Product.objects.create(client=existing, sku='A1', name='Before')
        enable_calculator_customer(self.pon.pk)
        product.refresh_from_db()
        self.assertEqual((product.pk, product.client_id, product.sku), (product.pk, existing.pk, 'A1'))

    def test_both_admin_routes_use_service_and_block_manual_fields(self):
        user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'secret')
        self.client.force_login(user)
        customer_url = reverse('admin:clients_customer_change', args=[self.pon.pk])
        response = self.client.get(customer_url)
        self.assertContains(response, 'Enable as Calculator Customer')
        self.assertContains(response, 'Not linked')

        add_url = reverse('admin:clients_client_add')
        response = self.client.post(add_url, {'code': 'FAKE', 'name': 'Forged', 'active': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Client.objects.exists())
        response = self.client.post(add_url, {'customer': str(self.special.pk), 'active': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Client.objects.exists())

        response = self.client.post(add_url, {'customer': str(self.pon.pk), 'active': 'on'})
        self.assertEqual(response.status_code, 302)
        self.pon.refresh_from_db()
        self.assertEqual((self.pon.linked_client.code, self.pon.linked_client.name), ('PON', 'Pon Bike'))
        response = self.client.get(customer_url)
        self.assertContains(response, 'Linked')
        self.assertNotContains(response, 'Enable as Calculator Customer')
        response = self.client.get(reverse('admin:clients_client_changelist'))
        self.assertContains(response, 'PON')

    def test_customer_action_uses_same_service_and_rejects_get(self):
        user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'secret')
        self.client.force_login(user)
        url = reverse('admin:clients_customer_enable', args=[self.pon.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Client.objects.get(code='PON').name, 'Pon Bike')
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(Client.objects.count(), 1)

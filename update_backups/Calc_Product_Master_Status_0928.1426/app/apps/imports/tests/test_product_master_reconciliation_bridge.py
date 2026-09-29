"""A global Product Master can be compared only inside an authorised Client scope."""

from hashlib import sha256
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.services import ADMINISTRATORS_GROUP
from apps.clients.models import Client, Customer
from apps.imports.models import (
    ExternalDataCorrectionMemory, ExternalDataFile, ProductCorrectionRound,
    ProductMaster, ProductReconciliationDecision, ProductSourceRow,
)
from apps.products.models import Product


class ProductMasterReadOnlyBridgeTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.sth = Client.objects.create(code='STH', name='Steadfast')
        self.pon = Client.objects.create(code='PON', name='Pon Bike')
        self.sth_customer = Customer.objects.create(
            code='STH', name='Steadfast', linked_client=self.sth, source_row_number=1)
        self.pon_customer = Customer.objects.create(
            code='PON', name='Pon Bike', linked_client=self.pon, source_row_number=2)
        Customer.objects.create(code='ABC', name='Unlinked', source_row_number=3)
        Product.objects.create(client=self.sth, sku='A1', name='Old STH')
        Product.objects.create(client=self.pon, sku='A1', name='Old PON')
        data = b'example product master bytes'
        self.master = ProductMaster(
            original_filename='products.xls', sha256=sha256(data).hexdigest(),
            file_size_bytes=len(data), status='VALIDATED',
            validation_summary={'customer_counts': {'STH': 102, 'PON': 1, 'ABC': 1}},
        )
        self.master.original_file.save('products.xls', ContentFile(data), save=False)
        self.master.save()
        self.superuser = get_user_model().objects.create_superuser(
            'admin', 'admin@example.test', 'password')

    @staticmethod
    def workbook(*args, **kwargs):
        rows = [{'customer': 'STH', 'code': f'STH-{i}', 'name': f'STH item {i}',
                 '_row_number': i + 2} for i in range(101)]
        rows.extend([
            {'customer': 'STH', 'code': 'A1', 'name': 'New STH', '_row_number': 103},
            {'customer': 'PON', 'code': 'A1', 'name': 'New PON', '_row_number': 104},
            {'customer': 'ABC', 'code': 'A1', 'name': 'Unlinked', '_row_number': 105},
            {'customer': 'MISSING', 'code': 'A1', 'name': 'Unknown', '_row_number': 106},
            {'customer': '', 'code': 'A1', 'name': 'No Customer', '_row_number': 107},
        ])
        return SimpleNamespace(
            headers=['CUSTOMER', 'code', 'name'], records=rows, rejected_rows=[],
            source_format='XLS', worksheet='products', header_row=1, warnings=[],
        )

    def compare(self, client):
        return reverse('admin:imports_productmaster_compare', args=[self.master.pk, client.pk])

    def test_superuser_sees_correct_client_and_late_rows_without_writes(self):
        self.client.force_login(self.superuser)
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.workbook):
            for client, own, foreign in ((self.sth, 'New STH', 'New PON'),
                                         (self.pon, 'New PON', 'New STH')):
                result = self.client.get(self.compare(client) + '?status=DIFFERENT')
                self.assertEqual(result.status_code, 200)
                self.assertContains(result, own)
                self.assertNotContains(result, foreign)
                self.assertNotContains(result, 'Unlinked')
                self.assertNotContains(result, 'Unknown')
                self.assertNotContains(result, 'No Customer')
                if client == self.sth:
                    self.assertEqual(result.context['summary']['source_rows'], 102)
                    self.assertEqual(result.context['summary']['different'], 1)
                else:
                    self.assertEqual(result.context['summary']['source_rows'], 1)
                    self.assertEqual(result.context['summary']['different'], 1)
            self.assertEqual(self.client.post(self.compare(self.sth)).status_code, 405)
        self.assertEqual(Product.objects.count(), 2)
        for model in (ProductSourceRow, ExternalDataFile, ProductReconciliationDecision,
                      ExternalDataCorrectionMemory, ProductCorrectionRound):
            self.assertEqual(model.objects.count(), 0)
        self.assertEqual(Customer.objects.get(code='STH').linked_client_id, self.sth.pk)

    def test_selected_internal_user_cannot_cross_client_by_url(self):
        user = get_user_model().objects.create_user('selected', password='pw', is_staff=True)
        profile = CalculatorUserProfile.objects.create(
            user=user, role='INTERNAL_USER', client_scope='SELECTED_CLIENTS')
        profile.allowed_clients.add(self.sth)
        user.user_permissions.add(Permission.objects.get(codename='view_productsourcerow'))
        self.client.force_login(user)
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.workbook) as reader:
            # The existing Admin middleware denies SELECTED_CLIENTS staff
            # even when they hold the row-view permission.
            self.assertEqual(self.client.get(self.compare(self.sth)).status_code, 403)
            self.assertEqual(self.client.get(self.compare(self.pon)).status_code, 403)
            reader.assert_not_called()
        self.assertEqual(ProductSourceRow.objects.count(), 0)
        self.assertEqual(ProductReconciliationDecision.objects.count(), 0)

    def test_approved_all_clients_administrator_can_compare_both(self):
        user = get_user_model().objects.create_user('all-admin', password='pw', is_staff=True)
        CalculatorUserProfile.objects.create(
            user=user, role='INTERNAL_USER', client_scope='ALL_CLIENTS')
        group = Group.objects.create(name=ADMINISTRATORS_GROUP)
        user.groups.add(group)
        user.user_permissions.add(Permission.objects.get(codename='view_productsourcerow'))
        self.client.force_login(user)
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.workbook):
            self.assertEqual(self.client.get(self.compare(self.sth)).status_code, 200)
            self.assertEqual(self.client.get(self.compare(self.pon)).status_code, 200)

    def test_customer_user_scope_and_unlinked_customer_are_enforced(self):
        user = get_user_model().objects.create_user('pon-user', password='pw')
        CalculatorUserProfile.objects.create(
            user=user, role='CUSTOMER_USER', client=self.pon, client_scope='SINGLE_CLIENT')
        user.user_permissions.add(Permission.objects.get(codename='view_productsourcerow'))
        self.client.force_login(user)
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.workbook) as reader:
            # Customer Users have no Django Admin access, including their own.
            self.assertNotEqual(self.client.get(self.compare(self.sth)).status_code, 200)
            self.assertNotEqual(self.client.get(self.compare(self.pon)).status_code, 200)
            reader.assert_not_called()
        self.client.force_login(self.superuser)
        self.pon_customer.linked_client = None
        self.pon_customer.save(update_fields=['linked_client'])
        self.assertEqual(self.client.get(self.compare(self.pon)).status_code, 404)

    def test_checksum_change_refuses_comparison(self):
        self.client.force_login(self.superuser)
        self.master.sha256 = '0' * 64
        self.master.save(update_fields=['sha256'])
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.workbook) as reader:
            self.assertEqual(self.client.get(self.compare(self.sth)).status_code, 404)
            reader.assert_not_called()

    def test_master_detail_links_only_linked_customers(self):
        self.client.force_login(self.superuser)
        result = self.client.get(reverse('admin:imports_productmaster_change', args=[self.master.pk]))
        self.assertContains(result, self.compare(self.sth))
        self.assertContains(result, self.compare(self.pon))
        self.assertNotContains(result, 'Compare ABC')

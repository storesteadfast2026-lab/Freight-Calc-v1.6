"""The Product Master detail reflects the existing comparison without writes."""

from hashlib import sha256
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.clients.models import Client, Customer
from apps.imports.models import ProductMaster
from apps.imports.tests import test_product_master_reconciliation_bridge as bridge_tests
from apps.products.models import Product


class ProductMasterOperationalStatusTests(TestCase):
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
        Customer.objects.create(
            code='PON', name='Pon Bike', linked_client=self.pon, source_row_number=2)
        Customer.objects.create(code='ABC', name='Unlinked', source_row_number=3)
        Product.objects.create(client=self.sth, sku='A1', name='Old STH')
        Product.objects.create(client=self.pon, sku='A1', name='Old PON')
        content = b'example product master bytes'
        self.master = ProductMaster(
            original_filename='products.xls', sha256=sha256(content).hexdigest(),
            file_size_bytes=len(content), status='VALIDATED',
            validation_summary={'rows_read': 124, 'customer_counts': {
                'STH': 123, 'PON': 1, 'ABC': 1}, 'status_counts': {'LINKED': 124}},
        )
        self.master.original_file.save('products.xls', ContentFile(content), save=False)
        self.master.save()
        self.client.force_login(get_user_model().objects.create_superuser(
            'admin', 'admin@example.test', 'password'))

    def detail(self):
        return self.client.get(reverse('admin:imports_productmaster_change',
                                       args=[self.master.pk]))

    def comparison(self, calculator_customer):
        return self.client.get(reverse('admin:imports_productmaster_compare',
                                       args=[self.master.pk, calculator_customer.pk]))

    def status_for(self, response, code):
        return next(item['status'] for item in response.context['operational_statuses']
                    if item['customer'].code == code)

    def test_every_linked_customer_matches_live_comparison(self):
        with patch('apps.imports.services.product_master.read_product_file',
                   side_effect=bridge_tests.ProductMasterReadOnlyBridgeTests.staged_workbook):
            detail = self.detail()
            self.assertEqual(detail.status_code, 200)
            html = detail.content.decode()
            self.assertLess(html.index('Validation overview'),
                            html.index('Operational status for STH'))
            self.assertIn('Operational status for PON', html)
            self.assertIn('Compare STH', html)
            self.assertIn('LINKED: 124', html)
            self.assertNotIn('Operational status for ABC', html)
            for code, client in (('STH', self.sth), ('PON', self.pon)):
                status = self.status_for(detail, code)
                compare = self.comparison(client).context
                for key in ('source_rows', 'operational_products', 'same',
                            'different', 'source_only', 'operational_only'):
                    self.assertEqual(status[key], compare['summary'][key], key)
                self.assertEqual(status['eligible_remaining'], compare['eligible_count'])
                self.assertEqual(status['blocked'],
                                 compare['summary']['source_only'] - compare['eligible_count'])
            self.assertEqual(self.status_for(detail, 'STH')['source_rows'], 123)
            self.assertEqual(self.status_for(detail, 'STH')['eligible_remaining'], 123)

    def test_counts_refresh_after_product_change_and_blocked_stays_pending(self):
        with patch('apps.imports.services.product_master.read_product_file',
                   side_effect=bridge_tests.ProductMasterReadOnlyBridgeTests.import_workbook):
            before = self.detail()
            self.assertEqual((self.status_for(before, 'STH')['source_only'],
                              self.status_for(before, 'STH')['eligible_remaining'],
                              self.status_for(before, 'STH')['blocked']), (2, 1, 1))
            Product.objects.create(client=self.sth, sku='NEW', name='Added operationally')
            after = self.detail()
            status = self.status_for(after, 'STH')
            compare = self.comparison(self.sth).context
            self.assertEqual((status['operational_products'], status['source_only'],
                              status['eligible_remaining'], status['blocked']), (2, 1, 0, 1))
            self.assertEqual(status['source_only'], compare['summary']['source_only'])
            self.assertEqual(status['eligible_remaining'], compare['eligible_count'])
            self.assertEqual(Product.objects.get(client=self.pon, sku='A1').name, 'Old PON')

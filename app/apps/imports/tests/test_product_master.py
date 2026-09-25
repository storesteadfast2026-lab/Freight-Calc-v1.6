"""Global Product Master upload and read-only validation."""
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.clients.models import Client, Customer
from apps.imports.forms import ExternalDataFileAdminForm
from apps.imports.models import ExternalDataFile, ProductMaster
from apps.imports.services.product_master import validate_product_master
from apps.products.models import Product


class ProductMasterTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.sth = Client.objects.create(code='STH', name='Steadfast')
        Customer.objects.create(code='STH', name='Steadfast', linked_client=self.sth, source_row_number=1)
        Customer.objects.create(code='PON', name='Pon Bike', source_row_number=2)
        self.product = Product.objects.create(client=self.sth, sku='A1', name='Existing')
        self.admin = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'secret')
        self.client.force_login(self.admin)

    def fake_reader(self, *args, **kwargs):
        rows = [{'customer': code, 'code': sku, '_row_number': index}
                for index, (code, sku) in enumerate(
                    [('STH', 'A1'), ('PON', 'A1'), ('MISSING', 'B2'), ('', 'C3')], start=2)]
        return SimpleNamespace(headers=['CUSTOMER', 'code'], records=rows, rejected_rows=[],
                               source_format='XLS', worksheet='products', header_row=1, warnings=[])

    def upload(self):
        return self.client.post(reverse('admin:imports_productmaster_add'), {
            'original_file': SimpleUploadedFile('products.xls', b'fake legacy xls bytes'),
            'client': self.sth.pk,
        })

    @patch('apps.imports.services.product_master.read_product_file')
    def test_upload_validate_preview_resolves_states_without_changes(self, reader):
        reader.side_effect = self.fake_reader
        self.assertEqual(self.upload().status_code, 302)
        master = ProductMaster.objects.get()
        self.assertEqual(master.status, 'UPLOADED')
        self.assertTrue(master.original_file.name.startswith('product_master/'))
        self.assertEqual(ExternalDataFile.objects.count(), 0)
        preview_url = reverse('admin:imports_productmaster_change', args=[master.pk])
        self.assertContains(self.client.get(preview_url), 'Validate')
        validate_url = reverse('admin:imports_productmaster_validate', args=[master.pk])
        self.assertEqual(self.client.get(validate_url).status_code, 405)
        self.assertEqual(self.client.post(validate_url).status_code, 302)
        master.refresh_from_db()
        summary = master.validation_summary
        self.assertEqual(master.status, 'VALIDATED')
        self.assertEqual(summary['status_counts'], {
            'LINKED': 1, 'UNLINKED': 1, 'UNKNOWN_CUSTOMER': 1, 'EMPTY_CUSTOMER': 1})
        self.assertEqual(summary['duplicate_customer_sku_pairs'], 0)
        self.assertEqual(summary['customer_counts'], {'(empty)': 1, 'MISSING': 1, 'PON': 1, 'STH': 1})
        self.assertEqual((summary['preview'][0]['sku'], summary['preview'][1]['sku']), ('A1', 'A1'))
        self.assertEqual(summary['preview'][0]['calculator_customer'], 'STH')
        self.assertEqual(summary['preview'][1]['calculator_customer'], '')
        view = self.client.get(preview_url)
        for status in ('LINKED', 'UNLINKED', 'UNKNOWN_CUSTOMER', 'EMPTY_CUSTOMER'):
            self.assertContains(view, status)
        self.assertEqual((Product.objects.count(), Client.objects.count(), Customer.objects.count()), (1, 1, 2))
        self.product.refresh_from_db()
        self.assertEqual((self.product.client_id, self.product.sku), (self.sth.pk, 'A1'))

    def test_invalid_workbook_is_recorded_without_operational_changes(self):
        self.upload()
        master = validate_product_master(ProductMaster.objects.get().pk, actor=self.admin)
        self.assertEqual(master.status, 'VALIDATION_FAILED')
        self.assertTrue(master.error_message)
        self.assertEqual(Product.objects.count(), 1)

    def test_customer_column_required(self):
        self.upload()
        with patch('apps.imports.services.product_master.read_product_file') as reader:
            source = self.fake_reader()
            source.headers = ['code']
            reader.return_value = source
            master = validate_product_master(ProductMaster.objects.get().pk)
        self.assertEqual(master.status, 'VALIDATION_FAILED')
        self.assertIn('CUSTOMER column', master.error_message)

    def test_no_client_selector_and_old_form_still_requires_client(self):
        self.assertNotContains(self.client.get(reverse('admin:imports_productmaster_add')), 'name="client"')
        self.assertIn('client', ExternalDataFileAdminForm.base_fields)
        self.assertFalse(ExternalDataFile._meta.get_field('client').null)

    def test_non_admin_cannot_access_global_master_by_id(self):
        self.upload()
        self.client.force_login(get_user_model().objects.create_user('other', password='secret', is_staff=True))
        self.assertNotEqual(self.client.get(reverse('admin:imports_productmaster_add')).status_code, 200)
        self.assertNotEqual(self.client.get(reverse('admin:imports_productmaster_change', args=[1])).status_code, 200)
        self.assertNotEqual(self.client.post(reverse('admin:imports_productmaster_validate', args=[1])).status_code, 302)

import io
import tempfile
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.audit.models import AuditEvent
from apps.carriers.models import Carrier, CarrierService, ClientCarrierConfig
from apps.clients.models import Client
from apps.imports.admin import ExternalDataFileAdmin
from apps.imports.models import ExternalDataFile, ProductSourceRow, StockSourceRow
from apps.imports.services.product_source import validate_product_source_file
from apps.imports.services.stock_source import validate_stock_source_file
from apps.imports.services.xlsx_reader import SourceImportError, calculate_sha256
from apps.products.models import Product
from apps.rates.models import FreightRate


PRODUCT_HEADERS = [
    'code', 'name', 'description', 'category', 'length', 'width', 'height',
    'cubic', 'quantity', 'weight', 'pallet', 'comment', 'status',
]
STOCK_HEADERS = [
    'stock_mov_no', 'stock_date', 'stock_customer', 'stock_product',
    'stock_sql_name', 'stock_quantity', 'stock_pallet', 'stock_group1',
    'stock_location', 'stock_class', 'stock_sql_stock_ref', 'stock_weight',
    'stock_cubic', 'stock_depot', 'stock_sql_group', 'stock_sql_group1',
    'stock_expiry', 'stock_pallet_ref', 'stock_serial_no', 'stock_status',
]


def build_xlsx(sheet_name, headers, rows):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


class ProductStockSourceTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.user = get_user_model().objects.create_user(
            username='source-admin', password='password', is_staff=True, is_superuser=True
        )
        self.client_obj = Client.objects.create(code='STH', name='Stenhoj Australia', active=True)
        self.product = Product.objects.create(
            client=self.client_obj,
            sku='CM245-AS',
            name='Approved hoist',
            length_m=Decimal('2.9300'),
            width_m=Decimal('1.1200'),
            height_m=Decimal('0.5000'),
            weight_kg=Decimal('825.0000'),
            cubic_m3=Decimal('1.641000'),
            freight_type='P',
        )
        carrier = Carrier.objects.create(code='TEST', name='Test Carrier')
        service = CarrierService.objects.create(carrier=carrier, service_code='ROAD')
        self.config = ClientCarrierConfig.objects.create(
            client=self.client_obj,
            carrier_service=service,
            ratecard='100',
            fuel_levy=Decimal('0.200000'),
        )
        self.rate = FreightRate.objects.create(
            client=self.client_obj,
            carrier_service=service,
            zone='A',
            freight_type='P',
            minimum_charge=Decimal('50.000000'),
        )

    def create_external_file(self, file_type, content, filename):
        external_file = ExternalDataFile.objects.create(
            client=self.client_obj,
            file_type=file_type,
            source_method='ADMIN_UPLOAD',
            original_filename=filename,
            status='UPLOADED',
            uploaded_by=self.user,
            file_size_bytes=len(content),
            sha256=calculate_sha256(content),
            mime_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        external_file.uploaded_file.save(filename, ContentFile(content), save=True)
        external_file.stored_path = external_file.uploaded_file.name
        external_file.save(update_fields=['stored_path'])
        return external_file

    def operational_snapshot(self):
        return {
            'products': list(Product.objects.order_by('pk').values()),
            'rates': list(FreightRate.objects.order_by('pk').values()),
            'configs': list(ClientCarrierConfig.objects.order_by('pk').values()),
        }

    def test_product_source_stores_reference_rows_without_operational_changes(self):
        content = build_xlsx('product_sth', PRODUCT_HEADERS, [[
            'CM245-AS', 'Electro-Hydraulic 2 Post Hoist', 'Approved source record',
            'STHHOI', 2930, 1120, 500, 1.641, 1, 825, 1, '', 'L',
        ]])
        external_file = self.create_external_file('PRODUCTS', content, 'product_sth.xlsx')
        before = self.operational_snapshot()

        summary = validate_product_source_file(external_file, actor=self.user)

        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertEqual(summary['rows_valid'], 1)
        self.assertFalse(summary['operational_tables_updated'])
        row = ProductSourceRow.objects.get(external_file=external_file)
        self.assertEqual(row.product_code_normalized, 'CM245-AS')
        self.assertEqual(row.weight_kg, Decimal('825'))
        self.assertEqual(row.cubic_m3, Decimal('1.641'))
        self.assertEqual(self.operational_snapshot(), before)
        self.assertTrue(AuditEvent.objects.filter(event_type='PRODUCT_SOURCE_VALIDATED').exists())

    def test_stock_source_stores_reference_rows_without_operational_changes(self):
        content = build_xlsx('stock_sth', STOCK_HEADERS, [[
            '9167910', '2026-07-20', 'STH', 'CM245-AS',
            'Electro-Hydraulic 2 Post Hoist', 105, 1, '', 'AA000', '', '',
            825, 1.641, '5W', '', 'STHHOI', '', '', 'SERIAL-1', 'I',
        ]])
        external_file = self.create_external_file('STOCK', content, 'stock_sth.xlsx')
        before = self.operational_snapshot()

        summary = validate_stock_source_file(external_file, actor=self.user)

        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertEqual(summary['rows_valid'], 1)
        self.assertFalse(summary['operational_tables_updated'])
        row = StockSourceRow.objects.get(external_file=external_file)
        self.assertEqual(row.product_code_normalized, 'CM245-AS')
        self.assertEqual(row.quantity, Decimal('105'))
        self.assertEqual(row.weight_kg, Decimal('825'))
        self.assertEqual(self.operational_snapshot(), before)
        self.assertTrue(AuditEvent.objects.filter(event_type='STOCK_SOURCE_VALIDATED').exists())

    def test_invalid_product_source_rejects_entire_staging_load(self):
        content = build_xlsx('product_sth', PRODUCT_HEADERS, [[
            'BAD-1', 'Invalid item', '', 'STHHOI', 100, 100, 100,
            0.001, 1, -5, 1, '', 'L',
        ]])
        external_file = self.create_external_file('PRODUCTS', content, 'product_sth.xlsx')
        before = self.operational_snapshot()

        with self.assertRaises(SourceImportError):
            validate_product_source_file(external_file, actor=self.user)

        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'VALIDATION_FAILED')
        self.assertEqual(ProductSourceRow.objects.filter(external_file=external_file).count(), 0)
        self.assertEqual(self.operational_snapshot(), before)
        self.assertTrue(
            AuditEvent.objects.filter(event_type='PRODUCT_SOURCE_VALIDATION_FAILED').exists()
        )

    def test_admin_uploads_and_validates_product_source(self):
        self.client.force_login(self.user)
        content = build_xlsx('product_sth', PRODUCT_HEADERS, [[
            'CM245-AS', 'Electro-Hydraulic 2 Post Hoist', '', 'STHHOI',
            2930, 1120, 500, 1.641, 1, 825, 1, '', 'L',
        ]])
        upload = SimpleUploadedFile(
            'product_sth.xlsx',
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response = self.client.post(
            reverse('admin:imports_externaldatafile_upload_products'),
            {'client': self.client_obj.pk, 'uploaded_file': upload, 'notes': 'Weekly source'},
        )
        self.assertEqual(response.status_code, 302)
        external_file = ExternalDataFile.objects.get(file_type='PRODUCTS')
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertEqual(ProductSourceRow.objects.filter(external_file=external_file).count(), 1)

    def test_admin_uploads_and_validates_stock_source(self):
        self.client.force_login(self.user)
        content = build_xlsx('stock_sth', STOCK_HEADERS, [[
            '9167910', '2026-07-20', 'STH', 'CM245-AS', 'Approved hoist',
            105, 1, '', 'AA000', '', '', 825, 1.641, '5W', '', 'STHHOI',
            '', '', 'SERIAL-1', 'I',
        ]])
        upload = SimpleUploadedFile(
            'stock_sth.xlsx',
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response = self.client.post(
            reverse('admin:imports_externaldatafile_upload_stock'),
            {'client': self.client_obj.pk, 'uploaded_file': upload, 'notes': 'Weekly stock'},
        )
        self.assertEqual(response.status_code, 302)
        external_file = ExternalDataFile.objects.get(file_type='STOCK')
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertEqual(StockSourceRow.objects.filter(external_file=external_file).count(), 1)

    def test_reference_source_has_no_activate_operation(self):
        content = build_xlsx('product_sth', PRODUCT_HEADERS, [[
            'CM245-AS', 'Approved hoist', '', 'STHHOI', 2930, 1120, 500,
            1.641, 1, 825, 1, '', 'L',
        ]])
        external_file = self.create_external_file('PRODUCTS', content, 'product_sth.xlsx')
        validate_product_source_file(external_file, actor=self.user)
        external_file.refresh_from_db()

        request = RequestFactory().get('/admin/imports/externaldatafile/')
        request.user = self.user
        model_admin = ExternalDataFileAdmin(ExternalDataFile, admin.site)
        links = str(model_admin.operation_links(external_file))
        self.assertIn('View rows', links)
        self.assertNotIn('Activate', links)
        self.assertNotIn('Rollback', links)

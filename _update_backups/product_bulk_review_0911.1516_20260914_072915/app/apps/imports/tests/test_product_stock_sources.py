import csv
import io
import tempfile
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.audit.models import AuditEvent
from apps.carriers.models import Carrier, CarrierService, ClientCarrierConfig
from apps.clients.models import Client
from apps.imports.admin import ExternalDataFileAdmin, ProductSourceRejectedRowAdmin
from apps.imports.models import (
    ExternalDataFile,
    ProductSourceRejectedRow,
    ProductSourceRow,
    StockSourceRow,
)
from apps.imports.services.product_source import (
    build_product_source_validation_report,
    normalize_product_sku,
    validate_product_source_file,
)
from apps.imports.services.product_repair import (
    ProductRepairError,
    approve_product_source_repair,
    build_product_repair_proposal,
    save_product_repair_proposal,
)
from apps.imports.services.stock_source import validate_stock_source_file
from apps.imports.services.xlsx_reader import SourceImportError, calculate_sha256, normalize_sku
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

    def test_sku_normalisation_preserves_meaningful_underscore(self):
        self.assertEqual(normalize_sku('0034'), '34')
        self.assertEqual(normalize_sku('20504089_'), '20504089_')

    def test_product_sku_normalisation_preserves_leading_zeroes(self):
        self.assertEqual(normalize_product_sku('0034'), '0034')
        self.assertEqual(normalize_product_sku('34'), '34')
        self.assertEqual(normalize_product_sku('  ab-01  '), 'AB-01')

    def test_products_csv_treats_leading_zero_codes_as_distinct(self):
        header = ','.join(PRODUCT_HEADERS)
        first = '0034,First product,,TEST,100,200,300,0.006,1,10,1,,L'
        second = '34,Second product,,TEST,400,500,600,0.120,1,20,1,,L'
        content = f'{header}\r\n{first}\r\n{second}\r\n'.encode('cp1252')
        external_file = self.create_external_file('PRODUCTS', content, 'products.csv')
        before = self.operational_snapshot()

        summary = validate_product_source_file(external_file, actor=self.user)

        self.assertEqual(summary['rows_valid'], 2)
        self.assertEqual(summary['rows_invalid'], 0)
        self.assertEqual(summary['duplicate_skus'], [])
        self.assertSetEqual(
            set(
                ProductSourceRow.objects.filter(external_file=external_file)
                .values_list('product_code_normalized', flat=True)
            ),
            {'0034', '34'},
        )
        self.assertEqual(self.operational_snapshot(), before)

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

    def test_products_csv_stores_valid_rows_and_isolates_malformed_rows(self):
        header = ','.join(PRODUCT_HEADERS)
        valid = 'CSV-1,Caf\xe9 hoist,Approved source record,STHHOI,2930,1120,500,1.641,1,825,1,,L'
        malformed = 'CSV-BAD,Malformed row,,STHHOI,100,100,100,0.001,1,5,1,L'
        content = f'{header}\r\n{valid}\r\n{malformed}\r\n'.encode('cp1252')
        external_file = self.create_external_file('PRODUCTS', content, 'products.csv')
        before = self.operational_snapshot()

        summary = validate_product_source_file(external_file, actor=self.user)

        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertEqual(summary['source_format'], 'CSV')
        self.assertEqual(summary['encoding'], 'cp1252')
        self.assertEqual(summary['rows_received'], 2)
        self.assertEqual(summary['rows_valid'], 1)
        self.assertEqual(summary['rows_invalid'], 1)
        self.assertEqual(summary['dimensions_complete'], 1)
        self.assertEqual(ProductSourceRow.objects.filter(external_file=external_file).count(), 1)
        rejected = ProductSourceRejectedRow.objects.get(external_file=external_file)
        self.assertEqual(rejected.source_row_number, 3)
        self.assertEqual(rejected.column_count, 12)
        self.assertEqual(self.operational_snapshot(), before)

        report = build_product_source_validation_report(external_file)
        self.assertIn('VALID,2,13,CSV-1,NEW', report)
        self.assertIn('REJECTED,3,12,CSV-BAD', report)
        report_rows = list(csv.reader(io.StringIO(report.lstrip('\ufeff'))))
        self.assertEqual({len(row) for row in report_rows}, {21})

    def test_repair_proposals_reconstruct_known_12_and_14_column_shapes(self):
        fourteen = [
            '20985', 'Wheel Sup Std 400mm Max875 Kg',
            'Wheel Support Device Standard" (400 mm) 1 Set = 4 Pieces',
            ' Capacity Per Item Max. 875 Kg"', 'NXPSPA', '0.000', '0.000',
            '0.000', '0.1520', '1.000', '40.0000', '0.000', '', 'L',
        ]
        proposal = build_product_repair_proposal(fourteen)
        self.assertEqual(proposal['code'], '20985')
        self.assertEqual(proposal['category'], 'NXPSPA')
        self.assertEqual(proposal['cubic_m3'], '0.1520')
        self.assertEqual(proposal['weight_kg'], '40.0000')
        self.assertIn('Pieces, Capacity', proposal['description'])

        twelve = [
            '3409',
            'SplitfireGaugeCupPodMount25/8",Splitfire Gauge Cup Pod Mount 2 5/8" '
            'Green Anodised Suit Electric Gauges"',
            'MTQGEN', '0.000', '0.000', '0.000', '0.0600', '1.000',
            '0.1500', '0.000', '', 'L',
        ]
        proposal = build_product_repair_proposal(twelve)
        self.assertEqual(proposal['name'], 'SplitfireGaugeCupPodMount25/8"')
        self.assertEqual(
            proposal['description'],
            'Splitfire Gauge Cup Pod Mount 2 5/8" Green Anodised Suit Electric Gauges',
        )
        self.assertEqual(proposal['source_status'], 'L')

        translogic_4307 = [
            '4307',
            'CaravanSpareWheelCover13",Caravan Spare Wheel Cover 13 Inch 7926"',
            'MTQGEN', '0.000', '0.000', '0.000', '0.0030', '1.000',
            '0.8000', '0.000', 'Unit 5x30x20cm 0.8kg', 'L',
        ]
        proposal = build_product_repair_proposal(translogic_4307)
        self.assertEqual(proposal['code'], '4307')
        self.assertEqual(proposal['name'], 'CaravanSpareWheelCover13"')
        self.assertEqual(
            proposal['description'],
            'Caravan Spare Wheel Cover 13 Inch 7926',
        )
        self.assertEqual(proposal['category'], 'MTQGEN')
        self.assertEqual(proposal['cubic_m3'], '0.0030')
        self.assertEqual(proposal['weight_kg'], '0.8000')
        self.assertEqual(proposal['comment'], 'Unit 5x30x20cm 0.8kg')
        self.assertEqual(proposal['source_status'], 'L')

    def _validated_products_with_rejected_20985(self):
        header = ','.join(PRODUCT_HEADERS)
        valid = 'CSV-OK,Valid row,,TEST,100,200,300,0.006,1,10,1,,L'
        malformed = (
            '"20985","Wheel Sup Std 400mm Max875 Kg",'
            '"Wheel Support Device "Standard" (400 mm) 1 Set = 4 Pieces, '
            'Capacity Per Item Max. 875 Kg","NXPSPA",0.000,0.000,0.000,'
            '0.1520,1.000,40.0000,0.000,"","L"'
        )
        content = f'{header}\r\n{valid}\r\n{malformed}\r\n'.encode('cp1252')
        external_file = self.create_external_file('PRODUCTS', content, 'products.csv')
        validate_product_source_file(external_file, actor=self.user)
        return external_file, ProductSourceRejectedRow.objects.get(
            external_file=external_file
        )

    def _approved_20985_payload(self):
        return {
            'code': '20985',
            'name': 'Wheel Sup Std 400mm Max875 Kg',
            'description': (
                'Wheel Support Device "Standard" (400 mm) 1 Set = 4 Pieces, '
                'Capacity Per Item Max. 875 Kg'
            ),
            'category': 'NXPSPA',
            'length_mm': Decimal('0'),
            'width_mm': Decimal('0'),
            'height_mm': Decimal('0'),
            'cubic_m3': Decimal('0.1520'),
            'quantity': Decimal('1'),
            'weight_kg': Decimal('40'),
            'pallet': Decimal('0'),
            'comment': '',
            'source_status': 'L',
        }

    def test_proposal_save_is_audited_and_does_not_enter_staging(self):
        external_file, rejected = self._validated_products_with_rejected_20985()
        before = self.operational_snapshot()
        initial_staging_count = ProductSourceRow.objects.filter(
            external_file=external_file
        ).count()

        save_product_repair_proposal(
            rejected.pk,
            payload=self._approved_20985_payload(),
            review_note='Checked against Translogic screen.',
            actor=self.user,
        )

        rejected.refresh_from_db()
        self.assertEqual(rejected.repair_status, 'PROPOSED')
        self.assertIsNone(rejected.staged_row_id)
        self.assertEqual(
            ProductSourceRow.objects.filter(external_file=external_file).count(),
            initial_staging_count,
        )
        self.assertEqual(self.operational_snapshot(), before)
        self.assertTrue(
            AuditEvent.objects.filter(event_type='PRODUCT_SOURCE_REPAIR_PROPOSED').exists()
        )

        with self.assertRaisesMessage(SourceImportError, 'saved repair reviews'):
            validate_product_source_file(external_file, actor=self.user)
        rejected.refresh_from_db()
        self.assertEqual(rejected.repair_status, 'PROPOSED')

    def test_approved_repair_adds_only_reference_staging_and_is_immutable(self):
        external_file, rejected = self._validated_products_with_rejected_20985()
        before = self.operational_snapshot()

        approve_product_source_repair(
            rejected.pk,
            payload=self._approved_20985_payload(),
            review_note='Confirmed against Translogic product 20985.',
            actor=self.user,
        )

        rejected.refresh_from_db()
        external_file.refresh_from_db()
        self.assertEqual(rejected.repair_status, 'APPROVED')
        self.assertIsNotNone(rejected.staged_row_id)
        repaired = rejected.staged_row
        self.assertEqual(repaired.product_code_normalized, '20985')
        self.assertEqual(repaired.description, self._approved_20985_payload()['description'])
        self.assertEqual(repaired.raw_data['source'], 'APPROVED_REPAIR')
        self.assertEqual(external_file.validation_summary['rows_repaired_approved'], 1)
        self.assertEqual(external_file.validation_summary['rows_pending_repair'], 0)
        self.assertEqual(external_file.validation_summary['rows_valid_effective'], 2)
        self.assertFalse(external_file.validation_summary['operational_tables_updated'])
        self.assertEqual(self.operational_snapshot(), before)
        self.assertTrue(
            AuditEvent.objects.filter(event_type='PRODUCT_SOURCE_REPAIR_APPROVED').exists()
        )

        report = build_product_source_validation_report(external_file)
        self.assertIn('VALID,3,13,20985,NEW', report)
        self.assertNotIn('REJECTED,3,14,20985', report)
        with self.assertRaisesMessage(ProductRepairError, 'already approved'):
            approve_product_source_repair(
                rejected.pk,
                payload=self._approved_20985_payload(),
                review_note='Second approval must fail.',
                actor=self.user,
            )

    def test_rejected_rows_admin_is_hidden_from_menu_but_context_page_is_accessible(self):
        external_file, rejected = self._validated_products_with_rejected_20985()
        self.client.force_login(self.user)
        request = RequestFactory().get('/admin/imports/')
        request.user = self.user
        model_admin = ProductSourceRejectedRowAdmin(
            ProductSourceRejectedRow, admin.site
        )
        self.assertEqual(model_admin.get_model_perms(request), {})

        index_response = self.client.get(reverse('admin:app_list', args=['imports']))
        self.assertEqual(index_response.status_code, 200)
        self.assertNotContains(index_response, 'Product source rejected rows')

        change_response = self.client.get(reverse(
            'admin:imports_productsourcerejectedrow_change', args=[rejected.pk]
        ))
        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, 'Approve into staging')

        external_file.refresh_from_db()
        file_admin = ExternalDataFileAdmin(ExternalDataFile, admin.site)
        self.assertIn('Review rejected rows', str(file_admin.operation_links(external_file)))

    def test_repair_rollback_cleanup_removes_only_approved_staging_row(self):
        external_file, rejected = self._validated_products_with_rejected_20985()
        before = self.operational_snapshot()
        approve_product_source_repair(
            rejected.pk,
            payload=self._approved_20985_payload(),
            review_note='Confirmed before rollback test.',
            actor=self.user,
        )

        call_command('rollback_product_repair_review')

        rejected.refresh_from_db()
        external_file.refresh_from_db()
        self.assertEqual(rejected.repair_status, 'PENDING')
        self.assertIsNone(rejected.staged_row_id)
        self.assertEqual(rejected.proposed_data, {})
        self.assertFalse(ProductSourceRow.objects.filter(
            external_file=external_file,
            product_code_normalized='20985',
        ).exists())
        self.assertEqual(external_file.validation_summary['rows_pending_repair'], 1)
        self.assertEqual(external_file.validation_summary['rows_repaired_approved'], 0)
        self.assertEqual(external_file.validation_summary['rows_valid_effective'], 1)
        self.assertEqual(self.operational_snapshot(), before)
        self.assertTrue(AuditEvent.objects.filter(
            event_type='PRODUCT_SOURCE_REPAIR_ROLLED_BACK'
        ).exists())

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

    def test_admin_uploads_and_validates_products_csv(self):
        self.client.force_login(self.user)
        content = (
            ','.join(PRODUCT_HEADERS)
            + '\r\nCSV-2,CSV product,,STHHOI,100,200,300,0.006,1,10,1,,L\r\n'
        ).encode('cp1252')
        upload = SimpleUploadedFile('products.csv', content, content_type='text/csv')

        response = self.client.post(
            reverse('admin:imports_externaldatafile_upload_products'),
            {'client': self.client_obj.pk, 'uploaded_file': upload, 'notes': 'CSV source'},
        )

        self.assertEqual(response.status_code, 302)
        external_file = ExternalDataFile.objects.get(file_type='PRODUCTS')
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertEqual(external_file.mime_type, 'text/csv')
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

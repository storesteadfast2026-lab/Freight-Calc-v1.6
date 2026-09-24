"""Same SKU across Translogic CUSTOMERS must never cross reconciliation boundaries."""

import io
import tempfile
import csv
import json
from pathlib import Path
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.clients.models import Client
from apps.authentication_gateway.models import CalculatorUserProfile
from apps.imports.models import ExternalDataFile, ProductSourceRow, ProductSourceRejectedRow
from apps.imports.services.product_source import validate_product_source_file, build_product_source_validation_report
from apps.imports.services.xlsx_reader import SourceImportError
from apps.imports.services.product_reconciliation_workspace import (
    build_workspace, save_product_reconciliation_decisions,
)
from apps.imports.services.product_reconciliation_apply import (
    apply_product_reconciliation, build_product_apply_plan,
)
from apps.imports.services.product_reconciliation_memory import product_memory_source_data
from apps.products.models import Product
from apps.products.selection import validate_product_selection


HEADERS = ('CUSTOMER', 'code', 'name', 'description', 'category', 'length',
           'width', 'height', 'cubic', 'quantity', 'weight', 'pallet', 'comment', 'status')


class ProductCustomerIdentityTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.client_obj = Client.objects.create(code='STH', name='STH')
        self.actor = get_user_model().objects.create_user('identity-admin', password='test', is_superuser=True)
        self.source = ExternalDataFile.objects.create(
            client=self.client_obj, file_type='PRODUCTS', original_filename='products.xlsx'
        )

    def upload(self, rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'products'
        sheet.append(HEADERS)
        for customer, sku, name in rows:
            sheet.append((customer, sku, name, 'Description', 'TEST', 1000, 1000, 1000,
                          Decimal('1.0'), 1, 10, 1, '', 'L'))
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        self.source.uploaded_file.save('products.xlsx', ContentFile(output.getvalue()), save=True)
        summary = validate_product_source_file(self.source, actor=self.actor)
        self.source.refresh_from_db()
        return summary

    def test_source_customer_duplicate_code_is_two_products_and_separate_decisions(self):
        Product.objects.create(client=self.client_obj, customer_code='ACME', sku='A1',
                               name='Old ACME', weight_kg=5)
        Product.objects.create(client=self.client_obj, customer_code='BETA', sku='A1',
                               name='Old BETA', weight_kg=5)
        summary = self.upload([('acme', 'A1', 'New ACME'), ('BETA', 'A1', 'New BETA')])
        self.assertEqual(summary['duplicate_skus'], [])
        self.assertEqual(summary['django_products_matched'], 2)
        self.assertEqual(set(ProductSourceRow.objects.values_list('customer_code', flat=True)), {'ACME', 'BETA'})
        rows, _ = build_workspace(self.source)
        self.assertEqual({row['sku'] for row in rows}, {'ACME::A1', 'BETA::A1'})
        saved = save_product_reconciliation_decisions(
            self.source, skus=['ACME::A1'],
            field_decisions={'name': 'SOURCE', 'description': 'OPERATIONAL',
                             'dimensions': 'OPERATIONAL', 'weight': 'OPERATIONAL',
                             'cubic': 'OPERATIONAL', 'freight_type': 'OPERATIONAL'},
            actor=self.actor,
        )
        self.assertEqual(saved[0].product_code_normalized, 'ACME::A1')
        self.assertTrue(build_product_apply_plan(self.source.pk)['can_apply'])
        apply_product_reconciliation(self.source.pk, actor=self.actor)
        self.assertEqual(Product.objects.get(customer_code='ACME').name, 'New ACME')
        self.assertEqual(Product.objects.get(customer_code='BETA').name, 'Old BETA')

    def test_unassigned_legacy_product_blocks_apply_and_removal(self):
        legacy = Product.objects.create(client=self.client_obj, sku='A1', name='Old')
        self.upload([('ACME', 'A1', 'New')])
        rows, summary = build_workspace(self.source)
        self.assertEqual(summary['unassigned_customer'], 1)
        self.assertEqual({r['status'] for r in rows}, {'SOURCE_ONLY', 'UNASSIGNED_CUSTOMER'})
        self.assertTrue(any('CUSTOMER assignment' in x for x in build_product_apply_plan(self.source.pk)['blockers']))
        legacy.customer_code = 'ACME'
        legacy.save(update_fields=['customer_code'])
        rows, summary = build_workspace(self.source)
        self.assertEqual(summary['unassigned_customer'], 0)
        self.assertEqual(rows[0]['status'], 'DIFFERENT')

    def test_selection_requires_customer_for_ambiguous_sku(self):
        a = Product.objects.create(client=self.client_obj, customer_code='ACME', sku='A1')
        Product.objects.create(client=self.client_obj, customer_code='BETA', sku='A1')
        with self.assertRaisesRegex(ValueError, 'select a Product'):
            validate_product_selection(self.client_obj, 'A1')
        validate_product_selection(self.client_obj, 'A1', 'ACME', a.pk)
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            validate_product_selection(self.client_obj, 'A1', 'BETA', a.pk)

    def test_calculator_search_labels_customer_and_rejects_ambiguous_input(self):
        Product.objects.create(client=self.client_obj, customer_code='ACME', sku='A1')
        Product.objects.create(client=self.client_obj, customer_code='BETA', sku='A1')
        CalculatorUserProfile.objects.create(
            user=self.actor, role='CUSTOMER_USER', client_scope='SINGLE_CLIENT',
            client=self.client_obj,
        )
        self.client.force_login(self.actor)
        response = self.client.get(reverse('product_autocomplete'), {'q': 'A1', 'client': 'STH'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({r['label'] for r in response.json()['results']}, {'ACME / A1', 'BETA / A1'})
        response = self.client.post(reverse('calculate_freight'),
                                    data=json.dumps({'client_code': 'STH', 'lines': [{'sku': 'A1'}]}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('select a Product', response.json()['error'])

    def test_legacy_applied_source_still_matches_after_customer_assignment(self):
        legacy_source = ExternalDataFile.objects.create(
            client=self.client_obj, file_type='PRODUCTS', original_filename='old.xls',
            status='VALIDATED', import_summary={}
        )
        product = Product.objects.create(client=self.client_obj, sku='A1', name='Old')
        ProductSourceRow.objects.create(external_file=legacy_source, source_row_number=3,
                                        product_code_raw='A1', product_code_normalized='A1', name='New')
        legacy_source.import_summary = {'product_reconciliation_apply_batches': [
            {'batch_id': 'historic', 'rolled_back_at': None, 'changes': [
                {'operation': 'UPDATE', 'before': {'id': product.pk, 'sku': 'A1'}}]}
        ]}
        legacy_source.save(update_fields=['import_summary'])
        product.customer_code = 'ACME'
        product.save(update_fields=['customer_code'])
        rows, _ = build_workspace(legacy_source)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['sku'], 'A1')
        self.assertEqual(rows[0]['product'].pk, product.pk)

    def test_same_customer_and_sku_in_source_is_rejected(self):
        with self.assertRaisesRegex(SourceImportError, 'Duplicate CUSTOMER / product code'):
            self.upload([('ACME', 'A1', 'First'), ('acme', 'A1', 'Second')])
        self.assertEqual(ProductSourceRow.objects.count(), 0)

    def test_customer_mapping_requires_individual_approval(self):
        product = Product.objects.create(client=self.client_obj, sku='A1')
        self.upload([('ACME', 'A1', 'New')])
        path = Path(self.temp.name) / 'review.csv'
        call_command('review_product_customers', source_id=self.source.pk, export=str(path))
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['assigned_customer'], 'ACME')
        self.assertEqual(rows[0]['approve'], '')
        self.assertEqual(Product.objects.get(pk=product.pk).customer_code, '')
        rows[0]['approve'] = 'YES'
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        call_command('review_product_customers', source_id=self.source.pk, apply=str(path))
        self.assertEqual(Product.objects.get(pk=product.pk).customer_code, 'ACME')

    def test_legacy_sku_text_cannot_impersonate_a_customer_identity(self):
        legacy = Product.objects.create(client=self.client_obj, sku='ACME::A1')
        Product.objects.create(client=self.client_obj, customer_code='ACME', sku='A1', name='Actual')
        self.upload([('ACME', 'A1', 'Source')])
        rows, summary = build_workspace(self.source)
        self.assertEqual(summary['unassigned_customer'], 1)
        matched = next(r for r in rows if r['source'])
        self.assertEqual(matched['product'].name, 'Actual')
        self.assertNotEqual(matched['product'].pk, legacy.pk)
        self.assertEqual(product_memory_source_data(matched)['customer_code'], 'ACME')

    def test_customer_csv_keeps_rejected_row_customer_and_reports_valid_customer(self):
        content = ('CUSTOMER,code,name,description,category,length,width,height,cubic,quantity,weight,pallet,comment,status\r\n'
                   'ACME,A1,Good,,TEST,1000,1000,1000,1,1,10,1,,L\r\n'
                   'BETA,A2,Bad,,TEST,1000,1000,1000,1,1,10,1,L\r\n').encode()
        self.source.original_filename = 'products.csv'
        self.source.uploaded_file.save('products.csv', ContentFile(content), save=True)
        self.source.save(update_fields=['original_filename'])
        summary = validate_product_source_file(self.source, actor=self.actor)
        self.source.refresh_from_db()
        self.assertEqual((summary['rows_valid'], summary['rows_invalid']), (1, 1))
        self.assertEqual(ProductSourceRejectedRow.objects.get().customer_code, 'BETA')
        report = build_product_source_validation_report(self.source)
        self.assertIn('customer,sku,comparison', report)
        self.assertIn('VALID,2,14,ACME,A1,NEW', report)

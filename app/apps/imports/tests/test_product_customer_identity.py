"""The CUSTOMER column selects a Client, never a second Product namespace."""
import io
import json
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.clients.models import Client
from apps.imports.models import ExternalDataFile, ProductSourceRow
from apps.imports.services.product_source import validate_product_source_file, build_product_source_validation_report
from apps.imports.services.product_reconciliation_workspace import build_workspace
from apps.imports.services.product_reconciliation_workspace import save_product_reconciliation_decisions
from apps.imports.services.product_reconciliation_apply import apply_product_reconciliation
from apps.imports.services.stock_source import validate_stock_source_file
from apps.products.models import Product


HEADERS = ('CUSTOMER', 'code', 'name', 'description', 'category', 'length',
           'width', 'height', 'cubic', 'quantity', 'weight', 'pallet', 'comment', 'status')


class ProductClientIdentityTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = override_settings(MEDIA_ROOT=self.temp.name)
        self.media.enable()
        self.addCleanup(self.media.disable)
        self.sth = Client.objects.create(code='STH', name='STH')
        self.pon = Client.objects.create(code='PON', name='PON')
        self.actor = get_user_model().objects.create_superuser('operator', 'operator@example.test', 'password')
        self.source = ExternalDataFile.objects.create(
            client=self.sth, file_type='PRODUCTS', original_filename='products.xlsx',
        )

    def upload(self, rows, *, actor=None):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'products'
        sheet.append(HEADERS)
        for customer, sku, name in rows:
            sheet.append((customer, sku, name, 'Description', 'TEST', 1000, 1000, 1000,
                          1, 1, 10, 1, '', 'L'))
        out = io.BytesIO()
        workbook.save(out)
        workbook.close()
        self.source.uploaded_file.save('products.xlsx', ContentFile(out.getvalue()), save=True)
        return validate_product_source_file(self.source, actor=actor or self.actor)

    def test_mixed_workbook_routes_same_sku_to_separate_client_sources(self):
        sth_product = Product.objects.create(client=self.sth, sku='A1', name='Old STH')
        pon_product = Product.objects.create(client=self.pon, sku='A1', name='Old PON')
        summary = self.upload([('STH', 'A1', 'New STH'), ('PON', 'A1', 'New PON')])
        self.assertEqual(summary['partition_client_codes'], ['PON'])
        sources = {source.client.code: source for source in ExternalDataFile.objects.all()}
        self.assertEqual(set(sources), {'STH', 'PON'})
        self.assertEqual(sources['PON'].validation_summary['partition_source_id'], self.source.pk)
        for client, product in [('STH', sth_product), ('PON', pon_product)]:
            source = sources[client]
            row = ProductSourceRow.objects.get(external_file=source)
            self.assertEqual((row.product_code_normalized, row.customer_code), ('A1', ''))
            self.assertEqual(row.raw_data['CUSTOMER'], client)
            rows, _ = build_workspace(source)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['product'].pk, product.pk)
            self.assertEqual(rows[0]['sku'], 'A1')
            report = build_product_source_validation_report(source)
            self.assertIn('customer,sku,comparison', report)
            self.assertIn(f',{client},A1,', report)
        self.assertNotEqual(sth_product.pk, pon_product.pk)

    def test_reconciliation_applies_only_to_selected_client(self):
        Product.objects.create(client=self.sth, sku='A1', name='Old STH', weight_kg=10)
        Product.objects.create(client=self.pon, sku='A1', name='Old PON', weight_kg=10)
        self.upload([('STH', 'A1', 'New STH'), ('PON', 'A1', 'New PON')])
        self.source.refresh_from_db()
        for source in ExternalDataFile.objects.order_by('pk'):
            rows, _ = build_workspace(source)
            self.assertEqual(rows[0]['status'], 'DIFFERENT')
        save_product_reconciliation_decisions(self.source, skus=['A1'],
            field_decisions={'name': 'SOURCE', 'description': 'OPERATIONAL',
                             'dimensions': 'OPERATIONAL', 'weight': 'OPERATIONAL',
                             'cubic': 'OPERATIONAL', 'freight_type': 'OPERATIONAL'},
            actor=self.actor)
        apply_product_reconciliation(self.source.pk, actor=self.actor)
        self.assertEqual(Product.objects.get(client=self.sth, sku='A1').name, 'New STH')
        self.assertEqual(Product.objects.get(client=self.pon, sku='A1').name, 'Old PON')

    def test_stock_compares_client_and_sku(self):
        from apps.imports.tests.test_product_stock_sources import STOCK_HEADERS
        Product.objects.create(client=self.sth, sku='A1')
        Product.objects.create(client=self.pon, sku='A1')
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'stock'
        sheet.append(STOCK_HEADERS)
        for client in ('STH', 'PON'):
            values = [''] * len(STOCK_HEADERS)
            values[0], values[2], values[3], values[5] = client + '-MOV', client, 'A1', 1
            sheet.append(values)
        out = io.BytesIO()
        workbook.save(out)
        source = ExternalDataFile.objects.create(client=self.sth, file_type='STOCK',
            original_filename='stock.xlsx')
        source.uploaded_file.save('stock.xlsx', ContentFile(out.getvalue()), save=True)
        summary = validate_stock_source_file(source, actor=self.actor)
        self.assertEqual(summary['django_products_matched'], 2)
        self.assertEqual(summary['stock_products_not_in_django'], 0)

    def test_unknown_client_fails_without_creating_product_or_partition(self):
        with self.assertRaisesRegex(Exception, 'Unknown or inactive Client'):
            self.upload([('STH', 'A1', 'STH'), ('ABC', 'A1', 'ABC')])
        self.assertEqual(ExternalDataFile.objects.count(), 1)
        self.assertFalse(ProductSourceRow.objects.exists())
        self.assertFalse(Product.objects.exists())

    def test_selected_internal_cannot_validate_another_client_partition(self):
        user = get_user_model().objects.create_user('selected', password='password', is_staff=True)
        profile = CalculatorUserProfile.objects.create(user=user, role='INTERNAL_USER',
            client_scope='SELECTED_CLIENTS')
        profile.allowed_clients.add(self.sth)
        with self.assertRaisesRegex(Exception, 'not authorised'):
            self.upload([('STH', 'A1', 'STH'), ('PON', 'A1', 'PON')], actor=user)
        self.assertEqual(ExternalDataFile.objects.count(), 1)
        self.assertFalse(ProductSourceRow.objects.exists())

    def test_client_sku_is_unique_within_client(self):
        Product.objects.create(client=self.sth, sku='A1')
        Product.objects.create(client=self.pon, sku='A1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.create(client=self.sth, sku='A1')

    def test_product_search_enforces_client_scope_in_backend(self):
        Product.objects.create(client=self.sth, sku='A1')
        pon_product = Product.objects.create(client=self.pon, sku='A1')
        Product.objects.create(client=self.pon, sku='PON-ONLY')
        for assigned, forbidden in [(self.sth, self.pon), (self.pon, self.sth)]:
            user = get_user_model().objects.create_user(assigned.code.lower(), password='password')
            CalculatorUserProfile.objects.create(user=user, role='CUSTOMER_USER',
                client_scope='SINGLE_CLIENT', client=assigned)
            self.client.force_login(user)
            response = self.client.get(reverse('product_autocomplete'), {'q': 'A1', 'client': assigned.code})
            self.assertEqual(response.status_code, 200)
            self.assertEqual([r['sku'] for r in response.json()['results']], ['A1'])
            self.assertEqual(self.client.get(reverse('product_autocomplete'),
                {'q': 'A1', 'client': forbidden.code}).status_code, 403)
            if assigned == self.sth:
                self.assertEqual(self.client.get(reverse('product_autocomplete'),
                    {'q': 'PON-ONLY'}).json()['results'], [])
                forged = self.client.post(reverse('calculate_freight'),
                    data=json.dumps({'client_code': 'STH', 'lines': [
                        {'sku': 'A1', 'product_id': pon_product.pk}]}),
                    content_type='application/json')
                self.assertEqual(forged.status_code, 400)

    def test_internal_all_and_selected_clients(self):
        from apps.authentication_gateway.services import allowed_clients_for
        Product.objects.create(client=self.sth, sku='STH-ONLY')
        Product.objects.create(client=self.pon, sku='PON-ONLY')
        for scope, expected in [('ALL_CLIENTS', {'STH', 'PON'}),
                                ('SELECTED_CLIENTS', {'STH'})]:
            user = get_user_model().objects.create_user(scope.lower(), password='password')
            profile = CalculatorUserProfile.objects.create(user=user, role='INTERNAL_USER',
                client_scope=scope)
            if scope == 'SELECTED_CLIENTS':
                profile.allowed_clients.add(self.sth)
            self.assertEqual(set(allowed_clients_for(user).values_list('code', flat=True)), expected)
            self.client.force_login(user)
            for client in (self.sth, self.pon):
                result = self.client.get(reverse('product_autocomplete'),
                    {'client': client.code, 'q': 'ONLY'})
                if client.code in expected:
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(len(result.json()['results']), 1)
                else:
                    self.assertEqual(result.status_code, 403)

    def test_admin_querysets_restrict_selected_internal_user(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from apps.imports.models import ExternalDataFile
        Product.objects.create(client=self.sth, sku='STH-ONLY')
        Product.objects.create(client=self.pon, sku='PON-ONLY')
        ExternalDataFile.objects.create(client=self.pon, file_type='PRODUCTS',
                                        original_filename='pon.xlsx')
        user = get_user_model().objects.create_user('selected-admin', password='password', is_staff=True)
        profile = CalculatorUserProfile.objects.create(user=user, role='INTERNAL_USER',
            client_scope='SELECTED_CLIENTS')
        profile.allowed_clients.add(self.sth)
        request = RequestFactory().get('/admin/')
        request.user = user
        product_admin = admin.site._registry[Product]
        source_admin = admin.site._registry[ExternalDataFile]
        self.assertEqual(list(product_admin.get_queryset(request).values_list('sku', flat=True)),
                         ['STH-ONLY'])
        self.assertEqual(list(source_admin.get_queryset(request).values_list('client__code', flat=True)),
                         ['STH'])

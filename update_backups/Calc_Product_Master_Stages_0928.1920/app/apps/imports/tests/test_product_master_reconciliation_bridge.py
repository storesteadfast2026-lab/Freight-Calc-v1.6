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
from apps.imports.services.product_reconciliation_apply import rollback_latest_product_apply


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

    @staticmethod
    def import_workbook(*args, **kwargs):
        def record(customer, sku, number, *, length=1200, pallet=1):
            return {'customer': customer, 'code': sku, 'name': f'{customer} {sku}',
                    'description': 'Imported from master', '_row_number': number,
                    'length': length, 'width': 800, 'height': 350, 'weight': 45,
                    'cubic': '0.336', 'pallet': pallet, 'status': 'L'}
        return SimpleNamespace(headers=['CUSTOMER', 'code'], records=[
            record('STH', 'NEW', 2), record('PON', 'NEW', 3),
            record('STH', 'INVALID', 4, length=-100),
            record('STH', 'NO_PALLET', 5, pallet=None),
            record('STH', 'A1', 6), record('ABC', 'OTHER', 7),
        ], rejected_rows=[], source_format='XLS', worksheet='products',
            header_row=1, warnings=[])

    def test_preview_import_apply_and_existing_rollback_are_client_scoped(self):
        self.client.force_login(self.superuser)
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.import_workbook):
            review = self.client.get(self.compare(self.sth) + '?status=SOURCE_ONLY')
            self.assertEqual(review.status_code, 200)
            self.assertContains(review, 'Select all eligible')
            self.assertContains(review, 'Row 4')
            self.assertContains(review, 'Excluded from import')
            self.assertNotContains(review, 'PON NEW')
            selected = self.client.post(self.compare(self.sth), {'action': 'review', 'skus': ['NEW']})
            self.assertEqual(selected.status_code, 302)
            preview_url = selected['Location']
            preview = self.client.get(preview_url)
            self.assertEqual(preview.status_code, 200)
            self.assertContains(preview, '1200')
            self.assertContains(preview, '1.2')
            self.assertContains(preview, 'Preview import')
            self.assertFalse(Product.objects.filter(client=self.sth, sku='NEW').exists())
            self.assertFalse(ExternalDataFile.objects.exists())
            token = preview.context['preview_token']
            apply = self.client.post(self.compare(self.sth), {'action': 'import', 'token': token})
            self.assertEqual(apply.status_code, 302)
            self.assertFalse([str(m) for m in __import__('django.contrib.messages', fromlist=['get_messages']).get_messages(apply.wsgi_request) if m.level >= 40])
            imported = Product.objects.get(client=self.sth, sku='NEW')
            self.assertTrue(imported.active)
            self.assertEqual(str(imported.length_m), '1.2000')
            self.assertEqual(imported.freight_type, 'P')
            self.assertFalse(Product.objects.filter(client=self.pon, sku='NEW').exists())
            self.assertEqual(Product.objects.get(client=self.pon, sku='A1').name, 'Old PON')
            staging = ExternalDataFile.objects.get()
            self.assertEqual(staging.client_id, self.sth.pk)
            self.assertEqual(staging.product_reconciliation_decisions.get().decision_status, 'APPLIED')
            self.assertEqual(staging.product_source_rows.get().customer_code, 'STH')
            self.assertEqual(staging.import_summary['product_reconciliation_apply_batches'][0]['changes'][0]['operation'], 'CREATE')
            rollback_latest_product_apply(staging.pk, actor=self.superuser)
            self.assertFalse(Product.objects.filter(client=self.sth, sku='NEW').exists())
            self.assertEqual(Product.objects.filter(client=self.pon, sku='A1').count(), 1)

    def test_post_rejects_wrong_customer_token_and_ineligible_selection(self):
        self.client.force_login(self.superuser)
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.import_workbook):
            wrong = self.client.post(self.compare(self.sth), {'action': 'review', 'skus': ['INVALID']})
            self.assertEqual(wrong.status_code, 302)
            selected = self.client.post(self.compare(self.sth), {'action': 'review', 'skus': ['NEW']})
            token = self.client.get(selected['Location']).context['preview_token']
            self.assertEqual(self.client.post(self.compare(self.pon),
                                              {'action': 'import', 'token': token}).status_code, 403)
            self.assertEqual(Product.objects.count(), 2)
            self.assertFalse(ExternalDataFile.objects.exists())

    def test_same_sku_in_two_customers_creates_distinct_products(self):
        self.client.force_login(self.superuser)
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.import_workbook):
            for client in (self.sth, self.pon):
                selected = self.client.post(self.compare(client), {'action': 'review', 'skus': ['NEW']})
                token = self.client.get(selected['Location']).context['preview_token']
                self.assertEqual(self.client.post(self.compare(client),
                                                  {'action': 'import', 'token': token}).status_code, 302)
        products = list(Product.objects.filter(sku='NEW').order_by('client__code'))
        self.assertEqual([product.client.code for product in products], ['PON', 'STH'])
        self.assertNotEqual(products[0].pk, products[1].pk)

    def test_preview_becomes_ineligible_if_product_is_created_before_apply(self):
        self.client.force_login(self.superuser)
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.import_workbook):
            selected = self.client.post(self.compare(self.sth), {'action': 'review', 'skus': ['NEW']})
            token = self.client.get(selected['Location']).context['preview_token']
            Product.objects.create(client=self.sth, sku='NEW', name='Created separately')
            result = self.client.post(self.compare(self.sth), {'action': 'import', 'token': token})
        self.assertEqual(result.status_code, 302)
        self.assertEqual(Product.objects.get(client=self.sth, sku='NEW').name, 'Created separately')
        self.assertFalse(ExternalDataFile.objects.exists())

    def test_applied_status_is_bound_to_matching_source_snapshot(self):
        self.client.force_login(self.superuser)
        from apps.imports.services.product_master import reconciliation_rows_for_customer
        with patch('apps.imports.services.product_master.read_product_file', side_effect=self.import_workbook):
            source = reconciliation_rows_for_customer(self.master, self.sth_customer, include_invalid=True)[0]
            prior = ExternalDataFile.objects.create(client=self.sth, file_type='PRODUCTS',
                                                     status='VALIDATED', original_filename='prior.xls')
            matching = next(row for row in source if row.product_code_normalized == 'A1')
            matching.pk = None
            matching.external_file = prior
            matching.save()
            ProductReconciliationDecision.objects.create(
                external_file=prior, product_code_normalized='A1', source_row_number=6,
                row_status='DIFFERENT', group_key='TEXT_ONLY',
                field_decisions={'name': 'OPERATIONAL'}, decision_status='APPLIED',
            )
            result = self.client.get(self.compare(self.sth) + '?status=DIFFERENT')
            self.assertContains(result, 'Open reconciliation')
            self.assertContains(result, 'Partially reviewed')
            matching.name = 'A different snapshot'
            matching.save(update_fields=['name'])
            result = self.client.get(self.compare(self.sth) + '?status=DIFFERENT')
            self.assertNotContains(result, 'Open reconciliation')
            self.assertContains(result, 'Needs review')

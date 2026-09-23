from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.clients.models import Client
from apps.imports.models import (
    ExternalDataFile,
    ProductReconciliationDecision,
    ProductReconciliationRule,
    ProductSourceRow,
)
from apps.imports.services.product_reconciliation_workspace import (
    build_workspace,
    preview_decision,
    save_product_reconciliation_decisions,
    save_reconciliation_rule,
)
from apps.products.models import Product


class ProductReconciliationWorkspaceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='reconciliation-admin',
            password='password',
            is_staff=True,
            is_superuser=True,
        )
        self.client_obj = Client.objects.create(
            code='STH',
            name='Stenhoj Australia',
            active=True,
        )
        self.external_file = ExternalDataFile.objects.create(
            client=self.client_obj,
            file_type='PRODUCTS',
            source_method='ADMIN_UPLOAD',
            original_filename='products.xls',
            status='VALIDATED',
            uploaded_by=self.user,
        )
        self.product = Product.objects.create(
            client=self.client_obj,
            sku='20772',
            name='120',
            description='80',
            length_m=Decimal('1.2000'),
            width_m=Decimal('0.8000'),
            height_m=Decimal('0.3500'),
            weight_kg=Decimal('70.0000'),
            cubic_m3=Decimal('0.336000'),
            freight_type='P',
        )
        ProductSourceRow.objects.create(
            external_file=self.external_file,
            source_row_number=6792,
            product_code_raw='20772',
            product_code_normalized='20772',
            name='Wheel Sup OffRd 500mm Max875kg',
            description='Wheel Support Device Offroad',
            category='TEST',
            length_mm=0,
            width_mm=0,
            height_mm=0,
            weight_kg=Decimal('45.2'),
            cubic_m3=Decimal('0.184'),
            quantity=1,
            pallet=1,
            source_status='L',
        )

    def product_snapshot(self):
        return list(Product.objects.order_by('pk').values())

    def test_workspace_groups_source_zero_dimensions(self):
        rows, summary = build_workspace(self.external_file)

        self.assertEqual(rows[0]['group_key'], 'SOURCE_DIMENSIONS_ZERO')
        self.assertEqual(summary['group_counts']['SOURCE_DIMENSIONS_ZERO'], 1)
        self.assertEqual(summary['draft_decisions'], 0)

    def test_bulk_draft_and_preview_do_not_change_product_or_freight_type(self):
        before = self.product_snapshot()
        decisions = save_product_reconciliation_decisions(
            self.external_file,
            skus=['20772'],
            field_decisions={
                'name': 'SOURCE',
                'description': 'SOURCE',
                'dimensions': 'OPERATIONAL',
                'weight': 'OPERATIONAL',
                'cubic': 'OPERATIONAL',
            },
            actor=self.user,
        )
        rows, summary = build_workspace(self.external_file)
        preview = preview_decision(rows[0], decisions[0])

        self.assertEqual(summary['draft_decisions'], 1)
        self.assertEqual(preview['proposed_values']['name'], 'Wheel Sup OffRd 500mm Max875kg')
        self.assertEqual(preview['proposed_values']['length_m'], Decimal('1.2000'))
        self.assertEqual(preview['proposed_values']['freight_type'], 'P')
        self.assertFalse(preview['operational_update_available'])
        self.assertEqual(self.product_snapshot(), before)
        self.assertTrue(AuditEvent.objects.filter(
            event_type='PRODUCT_RECONCILIATION_DRAFT_SAVED'
        ).exists())

    def test_individual_custom_values_remain_draft_only(self):
        before = self.product_snapshot()
        decision = save_product_reconciliation_decisions(
            self.external_file,
            skus=['20772'],
            field_decisions={
                'name': 'CUSTOM',
                'description': 'OPERATIONAL',
                'dimensions': 'CUSTOM',
                'weight': 'OPERATIONAL',
                'cubic': 'CUSTOM',
            },
            custom_values={
                'name': 'Reviewed wheel support',
                'length_m': '1.25',
                'width_m': '0.80',
                'height_m': '0.35',
                'cubic_m3': '0.350',
            },
            actor=self.user,
        )[0]

        self.assertEqual(decision.custom_values['name'], 'Reviewed wheel support')
        self.assertEqual(decision.custom_values['length_m'], '1.25')
        self.assertEqual(self.product_snapshot(), before)

    def test_reusable_rule_is_saved_without_applying_operational_changes(self):
        before = self.product_snapshot()
        rule = save_reconciliation_rule(
            self.external_file,
            name='Keep Calculator when source dimensions are zero',
            group_key='SOURCE_DIMENSIONS_ZERO',
            field_decisions={
                'name': 'SOURCE',
                'description': 'SOURCE',
                'dimensions': 'OPERATIONAL',
                'weight': 'OPERATIONAL',
                'cubic': 'OPERATIONAL',
            },
            actor=self.user,
        )

        self.assertTrue(rule.active)
        self.assertEqual(ProductReconciliationRule.objects.count(), 1)
        self.assertEqual(self.product_snapshot(), before)

    def test_workspace_screen_saves_selected_bulk_draft(self):
        before = self.product_snapshot()
        self.client.force_login(self.user)
        url = reverse(
            'admin:imports_externaldatafile_product_reconciliation',
            args=[self.external_file.pk],
        )

        response = self.client.post(url, {
            'workspace_action': 'save_bulk',
            'group': 'SOURCE_DIMENSIONS_ZERO',
            'selected_skus': ['20772'],
            'preset': 'KEEP_PHYSICAL_USE_SOURCE_TEXT',
            'scope': 'selected',
            'notes': 'Reviewed as a group.',
        })

        self.assertEqual(response.status_code, 302)
        decision = ProductReconciliationDecision.objects.get(
            external_file=self.external_file,
            product_code_normalized='20772',
        )
        self.assertEqual(decision.field_decisions['dimensions'], 'OPERATIONAL')
        self.assertEqual(self.product_snapshot(), before)

        response = self.client.get(f'{url}?group=SOURCE_DIMENSIONS_ZERO&mode=preview')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Preview draft decisions')
        self.assertContains(response, 'C/P is protected')
        self.assertContains(response, 'No operational Apply action is enabled')

"""Inline and field-scoped bulk decisions in the existing correction round."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.clients.models import Client
from apps.imports.models import (
    ExternalDataFile, ProductCorrectionDecision, ProductCorrectionRound,
    ProductSourceRow,
)
from apps.imports.services.product_correction_rounds import (
    CorrectionRoundError, apply_correction_round, bulk_field_candidates,
    correction_preview, rollback_correction_round, save_bulk_field_decisions,
    save_correction_decision, start_correction_round,
)
from apps.imports.services.product_reconciliation_apply import (
    apply_product_reconciliation, create_recommended_product_drafts,
)
from apps.products.models import Product


class ProductCorrectionBulkUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='correction-bulk-admin', password='password',
            is_staff=True, is_superuser=True,
        )
        self.client_obj = Client.objects.create(code='STH', name='STH', active=True)
        self.source = ExternalDataFile.objects.create(
            client=self.client_obj, file_type='PRODUCTS', status='VALIDATED',
            source_method='ADMIN_UPLOAD', original_filename='products.xls',
            uploaded_by=self.user,
        )
        self.product = Product.objects.create(
            client=self.client_obj, sku='A1', name='Operational product',
            description='Same', length_m=Decimal('1'), width_m=Decimal('1'),
            height_m=Decimal('1'), weight_kg=Decimal('10'),
            cubic_m3=Decimal('1'), freight_type='P',
        )
        ProductSourceRow.objects.create(
            external_file=self.source, source_row_number=2,
            product_code_raw='A1', product_code_normalized='A1',
            name='Source product', description='Same',
            length_mm=0, width_mm=0, height_mm=0,
            weight_kg=Decimal('12'), cubic_m3=Decimal('1.2'),
            quantity=1, pallet=1,
        )
        create_recommended_product_drafts(self.source, actor=self.user)
        apply_product_reconciliation(self.source.pk, actor=self.user)
        self.round = start_correction_round(self.source.pk, actor=self.user)
        self.url = reverse(
            'admin:imports_externaldatafile_product_reconciliation',
            args=[self.source.pk],
        )

    def _post_inline(self, product, *, weight='SOURCE', cubic='NO_CHANGE',
                     confirm_reopen=False):
        prefix = f'r{product.pk}'
        fields = {
            'sku': product.sku, 'name_authority': 'NO_CHANGE',
            'description_authority': 'NO_CHANGE',
            'dimensions_authority': 'NO_CHANGE', 'weight_authority': weight,
            'cubic_authority': cubic, 'freight_type_authority': 'NO_CHANGE',
            'notes': 'Verified against receiving report.',
        }
        data = {f'{prefix}-{key}': value for key, value in fields.items()}
        data.update({'correction_action': 'save_inline', 'round_id': self.round.pk,
                     'inline_sku': product.sku})
        if confirm_reopen:
            data['confirmed_reopen_skus'] = [product.sku]
        return self.client.post(f'{self.url}?mode=correction', data)

    def test_inline_table_shows_single_field_and_expandable_multiple_fields(self):
        second = Product.objects.create(
            client=self.client_obj, sku='B2', name='B2', description='Same',
            length_m=Decimal('1'), width_m=Decimal('1'), height_m=Decimal('1'),
            weight_kg=Decimal('10'), cubic_m3=Decimal('1'), freight_type='P',
        )
        ProductSourceRow.objects.create(
            external_file=self.source, source_row_number=3,
            product_code_raw='B2', product_code_normalized='B2',
            name='B2', description='Same', length_mm=1000, width_mm=1000,
            height_mm=1000, weight_kg=Decimal('12'), cubic_m3=Decimal('1'),
            quantity=1, pallet=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(f'{self.url}?mode=correction&round={self.round.pk}')
        self.assertContains(response, 'Select all visible')
        self.assertContains(response, 'Select all eligible in filtered results')
        self.assertContains(response, 'Multiple fields')
        self.assertContains(response, '3 different fields · expand')
        self.assertContains(response, f'r{second.pk}-weight_authority')
        self.assertContains(response, 'Source product')
        self.assertContains(response, 'Current Calculator')
        self.assertContains(response, 'B2')

    def test_inline_save_waits_for_apply_then_uses_existing_rollback(self):
        self.client.force_login(self.user)
        before = list(Product.objects.filter(pk=self.product.pk).values())[0]
        response = self._post_inline(self.product)
        self.assertEqual(response.status_code, 302)
        decision = ProductCorrectionDecision.objects.get(round=self.round, sku='A1')
        self.assertEqual(decision.field_decisions['weight'], 'SOURCE')
        self.assertEqual(decision.field_decisions['cubic'], 'NO_CHANGE')
        self.assertEqual(list(Product.objects.filter(pk=self.product.pk).values())[0], before)
        self.assertTrue(correction_preview(self.round)['can_apply'])
        apply_correction_round(self.round.pk, actor=self.user)
        self.product.refresh_from_db()
        self.assertEqual(self.product.weight_kg, Decimal('12'))
        self.assertEqual(self.product.cubic_m3, Decimal('1'))
        rollback_correction_round(self.round.pk, actor=self.user)
        self.assertEqual(list(Product.objects.filter(pk=self.product.pk).values())[0], before)

    def test_expanded_inline_custom_weight_and_source_cubic_keep_dimensions(self):
        self.client.force_login(self.user)
        prefix = f'r{self.product.pk}'
        payload = {
            'correction_action': 'save_inline', 'round_id': self.round.pk,
            'inline_sku': 'A1', f'{prefix}-sku': 'A1',
            f'{prefix}-name_authority': 'NO_CHANGE',
            f'{prefix}-description_authority': 'NO_CHANGE',
            f'{prefix}-dimensions_authority': 'OPERATIONAL',
            f'{prefix}-weight_authority': 'CUSTOM',
            f'{prefix}-custom_weight_kg': '13',
            f'{prefix}-cubic_authority': 'SOURCE',
            f'{prefix}-freight_type_authority': 'NO_CHANGE',
            f'{prefix}-notes': 'Measured weight and approved Source cubic.',
        }
        before = list(Product.objects.filter(pk=self.product.pk).values())[0]
        response = self.client.post(f'{self.url}?mode=correction', payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(Product.objects.filter(pk=self.product.pk).values())[0], before)
        response = self.client.get(
            f'{self.url}?mode=correction&round={self.round.pk}&status=DRAFT&group=MULTIPLE&q=A1'
        )
        self.assertContains(response, 'Draft saved')
        self.assertContains(response, '13')
        apply_correction_round(self.round.pk, actor=self.user)
        self.product.refresh_from_db()
        self.assertEqual(self.product.weight_kg, Decimal('13'))
        self.assertEqual(self.product.cubic_m3, Decimal('1.2'))
        self.assertEqual(self.product.length_m, Decimal('1'))

    def test_bulk_changes_only_one_field_and_clear_preserves_other_decisions(self):
        save_correction_decision(
            self.round.pk, sku='A1', field_decisions={
                'dimensions': 'NO_CHANGE', 'weight': 'SOURCE', 'cubic': 'NO_CHANGE',
                'name': 'NO_CHANGE', 'description': 'NO_CHANGE',
                'freight_type': 'NO_CHANGE',
            }, notes='Individual weight review.', actor=self.user,
        )
        old_product = list(Product.objects.filter(pk=self.product.pk).values())[0]
        result = save_bulk_field_decisions(
            self.round.pk, skus=['A1'], expected_eligible=['A1'],
            field='cubic', authority='SOURCE', notes='Bulk cubic review.', actor=self.user,
        )
        self.assertEqual(result['eligible'], ['A1'])
        decision = ProductCorrectionDecision.objects.get(round=self.round, sku='A1')
        self.assertEqual(decision.field_decisions['weight'], 'SOURCE')
        self.assertEqual(decision.field_decisions['cubic'], 'SOURCE')
        self.assertIn('Individual weight review.', decision.notes)
        self.assertEqual(list(Product.objects.filter(pk=self.product.pk).values())[0], old_product)
        save_bulk_field_decisions(
            self.round.pk, skus=['A1'], expected_eligible=['A1'],
            field='cubic', authority='CLEAR', notes='Review cubic later.', actor=self.user,
        )
        decision.refresh_from_db()
        self.assertEqual(decision.field_decisions['weight'], 'SOURCE')
        self.assertEqual(decision.field_decisions['cubic'], 'NO_CHANGE')
        self.assertTrue(correction_preview(self.round)['can_apply'])

    def test_bulk_preview_filters_server_side_and_rejects_another_client(self):
        other = Client.objects.create(code='PON', name='PON', active=True)
        Product.objects.create(client=other, sku='PON-ONLY', weight_kg=Decimal('1'))
        self.client.force_login(self.user)
        response = self.client.post(f'{self.url}?mode=correction', {
            'correction_action': 'preview_bulk_field', 'round_id': self.round.pk,
            'selected_skus': ['A1', 'PON-ONLY'], 'bulk_field': 'weight',
            'bulk_authority': 'SOURCE', 'bulk_reason': 'Warehouse weight check.',
        })
        self.assertContains(response, '1 included')
        self.assertContains(response, '1 excluded')
        self.assertEqual(self.round.decisions.count(), 0)
        token = response.context['bulk_field_preview']['token']
        response = self.client.post(f'{self.url}?mode=correction', {
            'correction_action': 'save_bulk_field', 'round_id': self.round.pk,
            'preview_token': token, 'bulk_reason': 'Warehouse weight check.',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.round.decisions.values_list('sku', flat=True)), ['A1'])
        with self.assertRaises(CorrectionRoundError):
            save_bulk_field_decisions(self.round.pk,
                skus=['PON-ONLY'], expected_eligible=['PON-ONLY'],
                field='weight', authority='SOURCE', notes='Unsafe.', actor=self.user)

    def test_source_zero_dimensions_cannot_be_bulk_applied_and_corrected_are_protected(self):
        result = bulk_field_candidates(self.round, ['A1'], field='dimensions', authority='SOURCE')
        self.assertEqual(result['eligible'], [])
        save_correction_decision(
            self.round.pk, sku='A1', field_decisions={'weight': 'SOURCE'},
            notes='Warehouse weight check.', actor=self.user,
        )
        apply_correction_round(self.round.pk, actor=self.user)
        later = start_correction_round(self.source.pk, actor=self.user)
        self.assertEqual(bulk_field_candidates(
            later, ['A1'], field='cubic', authority='SOURCE',
        )['eligible'], [])
        self.client.force_login(self.user)
        response = self.client.get(f'{self.url}?mode=correction&round={later.pk}&status=CORRECTED')
        self.assertContains(response, 'Already corrected in an applied round')
        self.round = later
        response = self._post_inline(self.product, cubic='SOURCE')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(later.decisions.count(), 0)
        response = self._post_inline(self.product, cubic='SOURCE', confirm_reopen=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(later.decisions.count(), 1)

    def test_selected_inline_rows_save_atomically_with_bulk_reason(self):
        second = Product.objects.create(
            client=self.client_obj, sku='B2', name='B2', description='Same',
            length_m=Decimal('1'), width_m=Decimal('1'), height_m=Decimal('1'),
            weight_kg=Decimal('10'), cubic_m3=Decimal('1'), freight_type='P',
        )
        ProductSourceRow.objects.create(
            external_file=self.source, source_row_number=3,
            product_code_raw='B2', product_code_normalized='B2', name='B2',
            description='Same', length_mm=1000, width_mm=1000, height_mm=1000,
            weight_kg=Decimal('12'), cubic_m3=Decimal('1'), quantity=1, pallet=1,
        )
        data = {
            'correction_action': 'save_selected_inline', 'round_id': self.round.pk,
            'selected_skus': ['A1', 'B2'], 'bulk_reason': 'Verified at the loading dock.',
        }
        for product in (self.product, second):
            prefix = f'r{product.pk}'
            data.update({
                f'{prefix}-sku': product.sku,
                f'{prefix}-name_authority': 'NO_CHANGE',
                f'{prefix}-description_authority': 'NO_CHANGE',
                f'{prefix}-dimensions_authority': 'NO_CHANGE',
                f'{prefix}-weight_authority': 'SOURCE',
                f'{prefix}-cubic_authority': 'NO_CHANGE',
                f'{prefix}-freight_type_authority': 'NO_CHANGE',
            })
        self.client.force_login(self.user)
        before = list(Product.objects.order_by('sku').values())
        response = self.client.post(f'{self.url}?mode=correction', data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.round.decisions.count(), 2)
        self.assertEqual(list(Product.objects.order_by('sku').values()), before)
        self.assertTrue(all(
            d.notes == 'Verified at the loading dock.' for d in self.round.decisions.all()
        ))
        data[f'r{second.pk}-sku'] = 'A1'
        response = self.client.post(f'{self.url}?mode=correction', data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.round.decisions.count(), 2)

    def test_filtered_select_all_and_clear_last_field_decision(self):
        self.client.force_login(self.user)
        response = self.client.post(f'{self.url}?mode=correction', {
            'correction_action': 'preview_bulk_field', 'round_id': self.round.pk,
            'select_all_filtered': 'yes', 'group': 'WEIGHT', 'status': 'UNREVIEWED',
            'bulk_field': 'weight', 'bulk_authority': 'OPERATIONAL',
            'bulk_reason': 'Calculator weight verified.',
        })
        self.assertContains(response, '1 included')
        token = response.context['bulk_field_preview']['token']
        response = self.client.post(f'{self.url}?mode=correction', {
            'correction_action': 'save_bulk_field', 'round_id': self.round.pk,
            'preview_token': token, 'bulk_reason': 'Calculator weight verified.',
        })
        self.assertEqual(response.status_code, 302)
        decision = ProductCorrectionDecision.objects.get(round=self.round, sku='A1')
        self.assertEqual(decision.field_decisions['weight'], 'OPERATIONAL')
        self.assertTrue(correction_preview(self.round)['can_apply'])
        result = save_bulk_field_decisions(
            self.round.pk, skus=['A1'], expected_eligible=['A1'],
            field='weight', authority='CLEAR', notes='No longer approved.', actor=self.user,
        )
        self.assertEqual(result['eligible'], ['A1'])
        self.assertFalse(self.round.decisions.exists())

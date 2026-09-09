from django.contrib import admin
from django.test import TestCase

from apps.clients.models import Client
from apps.imports.admin import (
    ExternalDataFileAdmin,
    ExternalDataReviewItemInline,
    PostcodesReviewItemForm,
)
from apps.imports.models import ExternalDataFile, ExternalDataReviewItem
from apps.imports.services.review import sync_postcodes_review_items
from apps.locations.models import Suburb


class PostcodesReviewPhase2ATests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            code='STH',
            name='Stenhoj Australia',
            active=True,
        )
        self.historical_alias = Suburb.objects.create(
            suburb_name='COLO VALE', state='NSW', postcode='2575'
        )
        self.historical_albany = Suburb.objects.create(
            suburb_name='ALBANY', state='WA', postcode='6330'
        )
        self.ftp_colovale = Suburb.objects.create(
            suburb_name='COLOVALE', state='NSW', postcode='2575'
        )
        self.ftp_albany = Suburb.objects.create(
            suburb_name='ALBANY', state='WA', postcode='6331'
        )
        self.external_file = ExternalDataFile.objects.create(
            client=self.client_obj,
            file_type='SUBURBS',
            source_method='FTP_DROP',
            original_filename='postcodes.csv',
            status='ACTIVE',
            validation_summary={
                'new_rows_preview': [
                    {
                        'suburb': 'COLOVALE', 'state': 'NSW', 'postcode': '2575',
                        'action': 'ADD', 'possible_alias': 'COLO VALE',
                    },
                    {
                        'suburb': 'ALBANY', 'state': 'WA', 'postcode': '6331',
                        'action': 'ADD', 'possible_alias': '',
                        'existing_same_suburb_state_postcodes': ['6330'],
                    },
                ],
            },
            import_summary={
                'created_rows': [
                    {
                        'id': self.ftp_colovale.pk, 'suburb': 'COLOVALE',
                        'state': 'NSW', 'postcode': '2575',
                    },
                    {
                        'id': self.ftp_albany.pk, 'suburb': 'ALBANY',
                        'state': 'WA', 'postcode': '6331',
                    },
                ],
            },
        )

    def test_sync_compares_historical_db_and_excludes_current_activation_rows(self):
        count_before = Suburb.objects.count()
        sync_postcodes_review_items(self.external_file)
        item = ExternalDataReviewItem.objects.get(
            external_file=self.external_file,
            row_key='SUBURBS|NSW|2575|COLOVALE',
        )
        ids = {row['id'] for row in item.current_data['historical_matches']}
        self.assertIn(self.historical_alias.pk, ids)
        self.assertNotIn(self.ftp_colovale.pk, ids)
        self.assertEqual(Suburb.objects.count(), count_before)

    def test_same_suburb_old_postcode_is_available_for_comparison(self):
        sync_postcodes_review_items(self.external_file)
        item = ExternalDataReviewItem.objects.get(
            external_file=self.external_file,
            row_key='SUBURBS|WA|6331|ALBANY',
        )
        matches = item.current_data['historical_matches']
        self.assertTrue(any(row['id'] == self.historical_albany.pk for row in matches))
        self.assertFalse(any(row['id'] == self.ftp_albany.pk for row in matches))

    def test_correction_fields_start_from_source_and_survive_resync(self):
        sync_postcodes_review_items(self.external_file)
        item = ExternalDataReviewItem.objects.get(
            external_file=self.external_file,
            row_key='SUBURBS|NSW|2575|COLOVALE',
        )
        self.assertEqual(item.corrected_suburb, 'COLOVALE')
        self.assertEqual(item.corrected_state, 'NSW')
        self.assertEqual(item.corrected_postcode, '2575')

        item.corrected_suburb = 'COLO VALE'
        item.decision = 'CORRECT_MANUALLY'
        item.notes = 'Confirmed spelling.'
        item.save(update_fields=['corrected_suburb', 'decision', 'notes'])
        sync_postcodes_review_items(self.external_file)
        item.refresh_from_db()
        self.assertEqual(item.corrected_suburb, 'COLO VALE')
        self.assertEqual(item.decision, 'CORRECT_MANUALLY')
        self.assertEqual(item.notes, 'Confirmed spelling.')

    def test_notes_and_manual_override_share_one_compact_control(self):
        form = PostcodesReviewItemForm()
        field = form.fields['review_controls']
        self.assertEqual(
            field.widget.__class__.__name__,
            'PostcodesReviewControlsWidget',
        )
        self.assertEqual(
            field.widget.widgets[0].__class__.__name__,
            'TextInput',
        )
        self.assertEqual(
            field.widget.widgets[0].attrs.get('placeholder'),
            'Review note',
        )

    def test_inline_keeps_only_compact_review_columns_in_same_row(self):
        inline = ExternalDataReviewItemInline(ExternalDataFile, admin.site)
        self.assertEqual(
            inline.fields,
            (
                'source_display',
                'selected_historical_suburb_id',
                'source_action_display',
                'decision',
                'review_controls',
            ),
        )

    def test_accept_source_uses_authoritative_source_values(self):
        sync_postcodes_review_items(self.external_file)
        item = ExternalDataReviewItem.objects.get(
            external_file=self.external_file,
            row_key='SUBURBS|NSW|2575|COLOVALE',
        )

        historical = Suburb.objects.get(
            suburb_name='COLO VALE',
            state='NSW',
            postcode='2575',
        )

        form = PostcodesReviewItemForm(
            data={
                'selected_historical_suburb_id': str(historical.pk),
                'decision': 'ACCEPT_SOURCE',
                'review_controls_0': '',
                'review_controls_1': 'COLO VALE',
                'review_controls_2': 'NSW',
                'review_controls_3': '2575',
            },
            instance=item,
        )
        self.assertTrue(form.is_valid(), form.errors)

        saved = form.save()
        self.assertEqual(saved.corrected_suburb, 'COLOVALE')
        self.assertEqual(saved.corrected_state, 'NSW')
        self.assertEqual(saved.corrected_postcode, '2575')

    def test_phase2a_has_no_operational_apply_method(self):
        model_admin = ExternalDataFileAdmin(ExternalDataFile, admin.site)
        self.assertFalse(hasattr(model_admin, 'apply_reviewed_corrections'))

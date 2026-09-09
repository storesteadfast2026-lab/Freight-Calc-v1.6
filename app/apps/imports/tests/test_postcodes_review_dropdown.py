from django.contrib import admin
from django.contrib.staticfiles import finders
from django.test import TestCase

from apps.clients.models import Client
from apps.imports.admin import ExternalDataReviewItemInline, PostcodesReviewItemForm
from apps.imports.models import ExternalDataFile, ExternalDataReviewItem
from apps.imports.services.review import sync_postcodes_review_items
from apps.locations.models import Suburb


class PostcodesHistoricalDropdownTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            code='STH',
            name='Stenhoj Australia',
            active=True,
        )
        self.current_alias = Suburb.objects.create(
            suburb_name='COLO VALE',
            state='NSW',
            postcode='2575',
        )
        self.generic_same_postcode = Suburb.objects.create(
            suburb_name='ALPINE',
            state='NSW',
            postcode='2575',
        )
        self.ftp_row = Suburb.objects.create(
            suburb_name='COLOVALE',
            state='NSW',
            postcode='2575',
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
                        'suburb': 'COLOVALE',
                        'state': 'NSW',
                        'postcode': '2575',
                        'action': 'ADD',
                        'possible_alias': 'COLO VALE',
                    },
                ],
            },
            import_summary={
                'created_rows': [
                    {
                        'suburb_id': self.ftp_row.pk,
                        'suburb': 'COLOVALE',
                        'state': 'NSW',
                        'postcode': '2575',
                    },
                ],
            },
        )
        sync_postcodes_review_items(self.external_file)
        self.item = ExternalDataReviewItem.objects.get(
            external_file=self.external_file
        )

    def test_dropdown_contains_only_direct_current_db_candidates(self):
        form = PostcodesReviewItemForm(instance=self.item)
        choices = dict(form.fields['selected_historical_suburb_id'].choices)

        self.assertIn(str(self.current_alias.pk), choices)
        self.assertNotIn(str(self.generic_same_postcode.pk), choices)
        self.assertNotIn(str(self.ftp_row.pk), choices)

    def test_first_current_db_candidate_is_preselected_when_none_saved(self):
        form = PostcodesReviewItemForm(instance=self.item)

        self.assertIsNone(self.item.selected_historical_suburb_id)
        self.assertEqual(
            form.initial['selected_historical_suburb_id'],
            str(self.current_alias.pk),
        )

    def test_saved_current_db_selection_has_priority_over_default_first(self):
        self.item.selected_historical_suburb_id = self.current_alias.pk
        self.item.save(update_fields=['selected_historical_suburb_id'])

        form = PostcodesReviewItemForm(instance=self.item)

        self.assertEqual(
            form.initial['selected_historical_suburb_id'],
            str(self.current_alias.pk),
        )

    def test_current_db_selection_is_reference_not_final_value_source(self):
        form = PostcodesReviewItemForm(
            data={
                'selected_historical_suburb_id': str(self.current_alias.pk),
                'decision': 'ACCEPT_SOURCE',
                'review_controls_0': '',
                'review_controls_1': 'COLO VALE',
                'review_controls_2': 'NSW',
                'review_controls_3': '2575',
            },
            instance=self.item,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(
            saved.selected_historical_suburb_id,
            self.current_alias.pk,
        )
        self.assertEqual(saved.corrected_suburb, 'COLOVALE')
        self.assertEqual(saved.corrected_state, 'NSW')
        self.assertEqual(saved.corrected_postcode, '2575')

    def test_legacy_decision_remains_visible_for_re_review(self):
        self.item.decision = 'USE_EXISTING_DB'
        self.item.save(update_fields=['decision'])

        form = PostcodesReviewItemForm(instance=self.item)
        choices = dict(form.fields['decision'].choices)

        self.assertIn('USE_EXISTING_DB', choices)
        self.assertIn('review again', choices['USE_EXISTING_DB'].lower())

    def test_inline_is_reduced_to_five_visible_review_columns(self):
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
        self.assertNotIn('review_status_display', inline.fields)
        self.assertNotIn('corrected_suburb', inline.fields)
        self.assertNotIn('corrected_state', inline.fields)
        self.assertNotIn('corrected_postcode', inline.fields)

    def test_compact_review_static_assets_exist(self):
        self.assertTrue(
            finders.find('admin/imports/postcodes_review_compact.css')
        )
        self.assertTrue(
            finders.find('admin/imports/postcodes_review_compact.js')
        )

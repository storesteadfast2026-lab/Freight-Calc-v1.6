from django.contrib import admin
from django.test import TestCase

from apps.clients.models import Client
from apps.imports.admin import ExternalDataReviewItemInline, PostcodesReviewItemForm
from apps.imports.models import ExternalDataFile, ExternalDataReviewItem
from apps.imports.services.review import (
    classify_postcodes_source_action,
    sync_postcodes_review_items,
)
from apps.locations.models import Suburb


class PostcodesSourceAuthorityScreenTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            code='STH',
            name='Stenhoj Australia',
            active=True,
        )

    def _file(self, source_row, created_rows=None):
        return ExternalDataFile.objects.create(
            client=self.client_obj,
            file_type='SUBURBS',
            source_method='FTP_DROP',
            original_filename='postcodes.csv',
            status='ACTIVE',
            validation_summary={'new_rows_preview': [source_row]},
            import_summary={'created_rows': created_rows or []},
        )

    def test_classifier_marks_exact_current_row_unchanged(self):
        result = classify_postcodes_source_action(
            {'suburb': 'JINGHI', 'state': 'QLD', 'postcode': '4410'},
            [
                {
                    'id': 1,
                    'suburb': 'JINGHI',
                    'state': 'QLD',
                    'postcode': '4410',
                    'match_type': 'EXACT_TRIPLET',
                }
            ],
        )
        self.assertEqual(result['action'], 'UNCHANGED')
        self.assertEqual(result['risk'], 'OK')

    def test_classifier_marks_no_current_match_add(self):
        result = classify_postcodes_source_action(
            {'suburb': 'JINGHI', 'state': 'QLD', 'postcode': '4410'},
            [],
        )
        self.assertEqual(result['action'], 'ADD')
        self.assertEqual(result['risk'], 'OK')

    def test_classifier_marks_different_current_candidate_replace_review(self):
        result = classify_postcodes_source_action(
            {'suburb': 'ALBANY', 'state': 'WA', 'postcode': '6331'},
            [
                {
                    'id': 10,
                    'suburb': 'ALBANY',
                    'state': 'WA',
                    'postcode': '6330',
                    'match_type': 'SAME_SUBURB_STATE',
                }
            ],
        )
        self.assertEqual(result['action'], 'REPLACE')
        self.assertEqual(result['risk'], 'REVIEW')

    def test_sync_defaults_final_values_to_authoritative_source(self):
        current = Suburb.objects.create(
            suburb_name='ALBANY',
            state='WA',
            postcode='6330',
        )
        external_file = self._file(
            {
                'suburb': 'ALBANY',
                'state': 'WA',
                'postcode': '6331',
                'action': 'ADD',
            }
        )

        sync_postcodes_review_items(external_file)

        item = ExternalDataReviewItem.objects.get(external_file=external_file)
        self.assertEqual(item.corrected_suburb, 'ALBANY')
        self.assertEqual(item.corrected_state, 'WA')
        self.assertEqual(item.corrected_postcode, '6331')
        self.assertEqual(item.current_data['source_action'], 'REPLACE')
        self.assertEqual(
            item.current_data['historical_matches'][0]['id'],
            current.pk,
        )

    def test_accept_source_saves_authoritative_source_without_final_columns(self):
        current = Suburb.objects.create(
            suburb_name='ALBANY',
            state='WA',
            postcode='6330',
        )
        external_file = self._file(
            {
                'suburb': 'ALBANY',
                'state': 'WA',
                'postcode': '6331',
                'action': 'ADD',
            }
        )
        sync_postcodes_review_items(external_file)
        item = ExternalDataReviewItem.objects.get(external_file=external_file)

        form = PostcodesReviewItemForm(
            data={
                'selected_historical_suburb_id': str(current.pk),
                'decision': 'ACCEPT_SOURCE',
                'review_controls_0': '',
                'review_controls_1': 'SHOULD NOT WIN',
                'review_controls_2': 'XX',
                'review_controls_3': '9999',
            },
            instance=item,
        )
        self.assertTrue(form.is_valid(), form.errors)

        saved = form.save()
        self.assertEqual(saved.corrected_suburb, 'ALBANY')
        self.assertEqual(saved.corrected_state, 'WA')
        self.assertEqual(saved.corrected_postcode, '6331')

    def test_replace_accept_source_requires_current_db_target(self):
        Suburb.objects.create(
            suburb_name='ALBANY',
            state='WA',
            postcode='6330',
        )
        external_file = self._file(
            {
                'suburb': 'ALBANY',
                'state': 'WA',
                'postcode': '6331',
                'action': 'ADD',
            }
        )
        sync_postcodes_review_items(external_file)
        item = ExternalDataReviewItem.objects.get(external_file=external_file)

        form = PostcodesReviewItemForm(
            data={
                'selected_historical_suburb_id': '',
                'decision': 'ACCEPT_SOURCE',
                'review_controls_0': '',
                'review_controls_1': 'ALBANY',
                'review_controls_2': 'WA',
                'review_controls_3': '6331',
            },
            instance=item,
        )
        self.assertFalse(form.is_valid())

    def test_manual_override_requires_notes(self):
        external_file = self._file(
            {
                'suburb': 'JINGHI',
                'state': 'QLD',
                'postcode': '4410',
                'action': 'ADD',
            }
        )
        sync_postcodes_review_items(external_file)
        item = ExternalDataReviewItem.objects.get(external_file=external_file)

        form = PostcodesReviewItemForm(
            data={
                'selected_historical_suburb_id': '',
                'decision': 'MANUAL_OVERRIDE',
                'review_controls_0': '',
                'review_controls_1': 'JINGHI HEIGHTS',
                'review_controls_2': 'QLD',
                'review_controls_3': '4410',
            },
            instance=item,
        )
        self.assertFalse(form.is_valid())

    def test_manual_override_saves_explicit_final_values_with_note(self):
        external_file = self._file(
            {
                'suburb': 'JINGHI',
                'state': 'QLD',
                'postcode': '4410',
                'action': 'ADD',
            }
        )
        sync_postcodes_review_items(external_file)
        item = ExternalDataReviewItem.objects.get(external_file=external_file)

        form = PostcodesReviewItemForm(
            data={
                'selected_historical_suburb_id': '',
                'decision': 'MANUAL_OVERRIDE',
                'review_controls_0': 'Confirmed exception.',
                'review_controls_1': 'JINGHI HEIGHTS',
                'review_controls_2': 'QLD',
                'review_controls_3': '4410',
            },
            instance=item,
        )
        self.assertTrue(form.is_valid(), form.errors)

        saved = form.save()
        self.assertEqual(saved.corrected_suburb, 'JINGHI HEIGHTS')
        self.assertEqual(saved.corrected_state, 'QLD')
        self.assertEqual(saved.corrected_postcode, '4410')
        self.assertEqual(saved.notes, 'Confirmed exception.')

    def test_current_db_selection_is_reference_only(self):
        current = Suburb.objects.create(
            suburb_name='COLO VALE',
            state='NSW',
            postcode='2575',
        )
        ftp_created = Suburb.objects.create(
            suburb_name='COLOVALE',
            state='NSW',
            postcode='2575',
        )
        external_file = self._file(
            {
                'suburb': 'COLOVALE',
                'state': 'NSW',
                'postcode': '2575',
                'action': 'ADD',
                'possible_alias': 'COLO VALE',
            },
            created_rows=[
                {
                    'suburb_id': ftp_created.pk,
                    'suburb': 'COLOVALE',
                    'state': 'NSW',
                    'postcode': '2575',
                }
            ],
        )
        sync_postcodes_review_items(external_file)
        item = ExternalDataReviewItem.objects.get(external_file=external_file)

        form = PostcodesReviewItemForm(
            data={
                'selected_historical_suburb_id': str(current.pk),
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
        self.assertEqual(saved.corrected_postcode, '2575')
        self.assertEqual(saved.selected_historical_suburb_id, current.pk)

    def test_inline_is_compact_source_current_action_decision_notes(self):
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

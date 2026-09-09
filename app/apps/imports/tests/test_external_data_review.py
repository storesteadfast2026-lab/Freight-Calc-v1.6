from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.clients.models import Client
from apps.imports.admin import ExternalDataFileAdmin, ExternalDataReviewItemInline
from apps.imports.models import ExternalDataFile, ExternalDataReviewItem
from apps.imports.services.review import sync_postcodes_review_items
from apps.locations.models import Suburb


class ExternalDataReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='review-admin',
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
                        'existing_same_suburb_state_postcodes': [],
                    },
                    {
                        'suburb': 'ALBANY',
                        'state': 'WA',
                        'postcode': '6331',
                        'action': 'ADD',
                        'possible_alias': '',
                        'existing_same_suburb_state_postcodes': ['6330'],
                    },
                ],
            },
            import_summary={
                'created_rows': [
                    {'id': 21156, 'suburb': 'COLOVALE', 'state': 'NSW', 'postcode': '2575'},
                    {'id': 21155, 'suburb': 'ALBANY', 'state': 'WA', 'postcode': '6331'},
                ],
            },
        )

    def test_sync_creates_review_items_without_operational_changes(self):
        before_suburbs = Suburb.objects.count()

        summary = sync_postcodes_review_items(self.external_file)

        self.assertEqual(summary['created'], 2)
        self.assertEqual(summary['current'], 2)
        self.assertEqual(ExternalDataReviewItem.objects.filter(
            external_file=self.external_file,
            is_current=True,
        ).count(), 2)
        self.assertEqual(Suburb.objects.count(), before_suburbs)

    def test_sync_is_idempotent_and_preserves_decision_and_notes(self):
        sync_postcodes_review_items(self.external_file)
        item = ExternalDataReviewItem.objects.get(
            external_file=self.external_file,
            source_data__suburb='COLOVALE',
        )
        item.decision = 'REMOVE_ADDED_ROW'
        item.notes = 'Reviewed spelling alias.'
        item.save(update_fields=['decision', 'notes'])

        summary = sync_postcodes_review_items(self.external_file)

        item.refresh_from_db()
        self.assertEqual(summary['created'], 0)
        self.assertEqual(item.decision, 'REMOVE_ADDED_ROW')
        self.assertEqual(item.notes, 'Reviewed spelling alias.')

    def test_sync_marks_old_preview_items_not_current(self):
        sync_postcodes_review_items(self.external_file)

        self.external_file.validation_summary = {
            'new_rows_preview': [
                {
                    'suburb': 'ALBANY',
                    'state': 'WA',
                    'postcode': '6331',
                    'action': 'ADD',
                },
            ],
        }
        self.external_file.save(update_fields=['validation_summary'])

        summary = sync_postcodes_review_items(self.external_file)

        self.assertEqual(summary['current'], 1)
        self.assertEqual(ExternalDataReviewItem.objects.filter(
            external_file=self.external_file,
            is_current=True,
        ).count(), 1)
        self.assertEqual(ExternalDataReviewItem.objects.filter(
            external_file=self.external_file,
            is_current=False,
        ).count(), 1)

    def test_non_suburbs_file_is_ignored(self):
        fuel_file = ExternalDataFile.objects.create(
            client=self.client_obj,
            file_type='FUEL',
            source_method='FTP_DROP',
            original_filename='fuel.csv',
            status='VALIDATED',
        )

        summary = sync_postcodes_review_items(fuel_file)

        self.assertTrue(summary['ignored'])
        self.assertEqual(ExternalDataReviewItem.objects.filter(
            external_file=fuel_file,
        ).count(), 0)

    def test_admin_inline_is_only_enabled_for_suburbs(self):
        model_admin = ExternalDataFileAdmin(ExternalDataFile, admin.site)

        suburbs_inlines = model_admin.get_inlines(None, self.external_file)
        self.assertEqual(suburbs_inlines, [ExternalDataReviewItemInline])

        fuel_file = ExternalDataFile(
            client=self.client_obj,
            file_type='FUEL',
            original_filename='fuel.csv',
        )
        self.assertEqual(model_admin.get_inlines(None, fuel_file), [])

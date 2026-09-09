from django.test import TestCase

from apps.clients.models import Client
from apps.imports.models import ExternalDataFile, ExternalDataReviewItem
from apps.imports.services.review import sync_postcodes_review_items
from apps.locations.models import Suburb


class PostcodesHistoricalComparisonCompactTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            code='STH',
            name='Stenhoj Australia',
            active=True,
        )

        self.colovale_historical = Suburb.objects.create(
            suburb_name='COLO VALE',
            state='NSW',
            postcode='2575',
            normalized_key='NSWCOLO VALE',
        )
        self.alpine = Suburb.objects.create(
            suburb_name='ALPINE',
            state='NSW',
            postcode='2575',
            normalized_key='NSWALPINE',
        )
        self.ayl = Suburb.objects.create(
            suburb_name='AYLMERTON',
            state='NSW',
            postcode='2575',
            normalized_key='NSWAYLMERTON',
        )
        self.ftp_colovale = Suburb.objects.create(
            suburb_name='COLOVALE',
            state='NSW',
            postcode='2575',
            normalized_key='NSWCOLOVALE',
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
                        'suburb_id': self.ftp_colovale.pk,
                        'suburb': 'COLOVALE',
                        'state': 'NSW',
                        'postcode': '2575',
                    },
                ],
            },
        )

    def test_real_suburb_id_from_import_summary_is_excluded(self):
        sync_postcodes_review_items(self.external_file)

        item = ExternalDataReviewItem.objects.get(external_file=self.external_file)
        matches = item.current_data['historical_matches']
        ids = {match['id'] for match in matches}

        self.assertNotIn(self.ftp_colovale.pk, ids)
        self.assertIn(self.colovale_historical.pk, ids)

    def test_generic_same_postcode_suburbs_are_counted_not_listed(self):
        sync_postcodes_review_items(self.external_file)

        item = ExternalDataReviewItem.objects.get(external_file=self.external_file)
        matches = item.current_data['historical_matches']
        matched_names = {match['suburb'] for match in matches}

        self.assertEqual(matched_names, {'COLO VALE'})
        self.assertEqual(item.current_data['same_state_postcode_other_count'], 2)

    def test_sync_does_not_change_locations_suburb(self):
        before = list(
            Suburb.objects.order_by('pk').values_list(
                'pk', 'suburb_name', 'state', 'postcode'
            )
        )

        sync_postcodes_review_items(self.external_file)

        after = list(
            Suburb.objects.order_by('pk').values_list(
                'pk', 'suburb_name', 'state', 'postcode'
            )
        )
        self.assertEqual(after, before)

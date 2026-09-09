from io import StringIO
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.clients.models import Client
from apps.imports.models import ExternalDataFile
from apps.imports.services.postcodes import (
    PostcodesImportError,
    parse_postcodes_rows,
    snapshot_ftp_postcodes_file,
    validate_postcodes_file,
)
from apps.locations.models import Suburb


VALID = b'''index,suburb,state,postcode\nACTONACT2601,ACTON,ACT,2601\nBURONGANSW2739,BURONGA,NSW,2739\nALICE SPRINGSNT0870,ALICE SPRINGS,NT,0870\n'''


class FTPPostcodesImportTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.client_obj = Client.objects.create(code='STH', name='Stenhoj Australia', active=True)

    def _snapshot(self, content=VALID):
        source = Path(self.media_dir.name) / 'postcodes.csv'
        source.write_bytes(content)
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            return snapshot_ftp_postcodes_file(client=self.client_obj, filename='postcodes.csv')

    def test_schema_and_leading_zero_postcode_are_preserved(self):
        rows, excluded = parse_postcodes_rows(VALID)
        self.assertEqual(excluded, [])
        alice = [row for row in rows if row['suburb'] == 'ALICE SPRINGS'][0]
        self.assertEqual(alice['postcode'], '0870')
        self.assertEqual(alice['normalized_key'], 'NTALICE SPRINGS')

    def test_missing_required_column_is_rejected(self):
        content = b'index,suburb,state\nACTONACT2601,ACTON,ACT\n'
        with self.assertRaisesMessage(PostcodesImportError, 'missing required column'):
            parse_postcodes_rows(content)

    def test_index_mismatch_is_rejected(self):
        content = b'index,suburb,state,postcode\nWRONG,ACTON,ACT,2601\n'
        with self.assertRaisesMessage(PostcodesImportError, 'index mismatch'):
            parse_postcodes_rows(content)

    def test_duplicate_triplet_is_rejected(self):
        content = (
            b'index,suburb,state,postcode\n'
            b'ACTONACT2601,ACTON,ACT,2601\n'
            b'ACTONACT2601,ACTON,ACT,2601\n'
        )
        with self.assertRaises(PostcodesImportError):
            parse_postcodes_rows(content)

    def test_non_australian_and_zero_postcode_rows_are_excluded_not_silently_loaded(self):
        content = (
            VALID
            + b'PRETORIA GAUTENGSAF0181,PRETORIA GAUTENG,SAF,0181\n'
            + b'ERRORSA0000,ERROR,SA,0000\n'
        )
        rows, excluded = parse_postcodes_rows(content)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(excluded), 2)
        self.assertTrue(any('non-Australian state SAF' in row['reason'] for row in excluded))
        self.assertTrue(any('invalid Australian postcode 0000' in row['reason'] for row in excluded))

    def test_same_suburb_state_with_multiple_postcodes_is_allowed(self):
        content = (
            b'index,suburb,state,postcode\n'
            b'CANBERRAACT2600,CANBERRA,ACT,2600\n'
            b'CANBERRAACT2601,CANBERRA,ACT,2601\n'
        )
        rows, excluded = parse_postcodes_rows(content)
        self.assertEqual(len(rows), 2)
        self.assertEqual(excluded, [])

    def test_validation_builds_delta_without_changing_suburb_table(self):
        Suburb.objects.create(
            suburb_name='ACTON', state='ACT', postcode='2601', normalized_key='ACTACTON'
        )
        Suburb.objects.create(
            suburb_name='LEGACY PLACE', state='SA', postcode='5000', normalized_key='SALEGACY PLACE'
        )
        external_file, _ = self._snapshot()
        before = set(Suburb.objects.values_list('suburb_name', 'state', 'postcode'))
        summary = validate_postcodes_file(external_file)
        after = set(Suburb.objects.values_list('suburb_name', 'state', 'postcode'))
        self.assertEqual(before, after)
        self.assertEqual(summary['existing_matches'], 1)
        self.assertEqual(summary['would_add'], 2)
        self.assertEqual(summary['current_not_in_source'], 1)
        self.assertFalse(summary['database_updated'])
        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'VALIDATED')

    def test_snapshot_is_idempotent_and_source_is_preserved(self):
        source = Path(self.media_dir.name) / 'postcodes.csv'
        source.write_bytes(VALID)
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            first, created_first = snapshot_ftp_postcodes_file(client=self.client_obj)
            second, created_second = snapshot_ftp_postcodes_file(client=self.client_obj)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertTrue(source.exists())
        self.assertNotEqual(Path(first.uploaded_file.path).resolve(), source.resolve())

    def test_command_is_validation_only_and_reuses_summary(self):
        source = Path(self.media_dir.name) / 'postcodes.csv'
        source.write_bytes(VALID)
        first_output = StringIO()
        second_output = StringIO()
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            call_command('process_uploaded_postcodes', '--client', 'STH', stdout=first_output)
            call_command('process_uploaded_postcodes', '--client', 'STH', stdout=second_output)
        self.assertEqual(Suburb.objects.count(), 0)
        external_file = ExternalDataFile.objects.get(file_type='SUBURBS', source_method='FTP_DROP')
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertIn('NO SUBURBS OR POSTCODES WERE ADDED', first_output.getvalue())
        self.assertIn('Reusing the existing validation summary', second_output.getvalue())

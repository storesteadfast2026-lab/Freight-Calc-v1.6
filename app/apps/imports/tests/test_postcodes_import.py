from io import StringIO
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.clients.models import Client
from apps.carriers.models import Carrier, CarrierService
from apps.imports.models import ExternalDataFile
from apps.imports.services.postcodes import (
    POSTCODES_ACTIVATION_POLICY,
    POSTCODES_POLICY_VERSION,
    PostcodesImportError,
    activate_postcodes_file,
    parse_postcodes_rows,
    rollback_postcodes_file,
    snapshot_ftp_postcodes_file,
    validate_postcodes_file,
)
from apps.locations.models import Suburb
from apps.rates.models import FreightZone


VALID = b'''index,suburb,state,postcode\nACTONACT2601,ACTON,ACT,2601\nBURONGANSW2739,BURONGA,NSW,2739\nALICE SPRINGSNT0870,ALICE SPRINGS,NT,0870\n'''


class FTPPostcodesImportTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.client_obj = Client.objects.create(code='STH', name='Stenhoj Australia', active=True)
        carrier = Carrier.objects.create(code='TEST', name='Test Carrier', active=True)
        self.carrier_service = CarrierService.objects.create(
            carrier=carrier, service_code='ROAD', service_name='Road', active=True
        )

    def _source_path(self):
        return Path(self.media_dir.name) / 'postcodes.csv'

    def _snapshot(self, content=VALID):
        source = self._source_path()
        source.write_bytes(content)
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            return snapshot_ftp_postcodes_file(client=self.client_obj, filename='postcodes.csv')

    def _validated_snapshot(self, content=VALID):
        external_file, _ = self._snapshot(content)
        validate_postcodes_file(external_file)
        external_file.refresh_from_db()
        return external_file

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

    def test_validation_builds_add_only_delta_without_changing_suburb_table(self):
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
        self.assertEqual(summary['existing_confirmed_in_current_source'], 1)
        self.assertEqual(summary['new_rows_to_add'], 2)
        self.assertEqual(summary['existing_not_in_current_source_preserved'], 1)
        self.assertEqual(summary['policy_version'], POSTCODES_POLICY_VERSION)
        self.assertEqual(summary['activation_policy'], POSTCODES_ACTIVATION_POLICY)
        self.assertFalse(summary['database_updated'])
        self.assertTrue(summary['activation_available'])
        self.assertFalse(summary['update_existing_allowed'])
        self.assertFalse(summary['delete_existing_allowed'])
        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'VALIDATED')

    def test_likely_alias_is_diagnostic_only_and_row_remains_addable(self):
        content = b'index,suburb,state,postcode\nNEWFARMQLD4005,NEWFARM,QLD,4005\n'
        Suburb.objects.create(
            suburb_name='NEW FARM', state='QLD', postcode='4005', normalized_key='QLDNEW FARM'
        )
        external_file, _ = self._snapshot(content)
        summary = validate_postcodes_file(external_file)
        row = summary['new_rows_preview'][0]
        self.assertEqual(summary['new_rows_to_add'], 1)
        self.assertEqual(row['action'], 'ADD')
        self.assertEqual(row['possible_alias'], 'NEW FARM')
        self.assertTrue(row['diagnostic_only'])
        self.assertEqual(Suburb.objects.count(), 1)

    def test_same_suburb_different_postcode_is_new_not_conflict(self):
        content = b'index,suburb,state,postcode\nALBANYWA6331,ALBANY,WA,6331\n'
        Suburb.objects.create(
            suburb_name='ALBANY', state='WA', postcode='6330', normalized_key='WAALBANY'
        )
        external_file, _ = self._snapshot(content)
        summary = validate_postcodes_file(external_file)
        row = summary['new_rows_preview'][0]
        self.assertEqual(summary['new_rows_to_add'], 1)
        self.assertEqual(row['action'], 'ADD')
        self.assertEqual(row['existing_same_suburb_state_postcodes'], ['6330'])

    def test_snapshot_is_idempotent_and_source_is_preserved(self):
        source = self._source_path()
        source.write_bytes(VALID)
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            first, created_first = snapshot_ftp_postcodes_file(client=self.client_obj)
            second, created_second = snapshot_ftp_postcodes_file(client=self.client_obj)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertTrue(source.exists())
        self.assertNotEqual(Path(first.uploaded_file.path).resolve(), source.resolve())

    def test_command_is_validation_only_and_reuses_current_summary(self):
        source = self._source_path()
        source.write_bytes(VALID)
        first_output = StringIO()
        second_output = StringIO()
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            call_command('process_uploaded_postcodes', '--client', 'STH', stdout=first_output)
            call_command('process_uploaded_postcodes', '--client', 'STH', stdout=second_output)
        self.assertEqual(Suburb.objects.count(), 0)
        external_file = ExternalDataFile.objects.get(file_type='SUBURBS', source_method='FTP_DROP')
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertIn('THE SUBURB MASTER WAS NOT CHANGED', first_output.getvalue())
        self.assertIn('Reusing the existing ADD-ONLY validation summary', second_output.getvalue())

    def test_command_revalidates_legacy_phase2_summary_for_identical_snapshot(self):
        source = self._source_path()
        source.write_bytes(VALID)
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            external_file, _ = snapshot_ftp_postcodes_file(client=self.client_obj)
            external_file.status = 'VALIDATED'
            external_file.validation_summary = {
                'source_format': 'FTP_POSTCODES',
                'cross_validation_version': 2,
                'database_updated': False,
            }
            external_file.save(update_fields=['status', 'validation_summary'])
            output = StringIO()
            call_command('process_uploaded_postcodes', '--client', 'STH', stdout=output)
        external_file.refresh_from_db()
        self.assertEqual(external_file.validation_summary.get('policy_version'), POSTCODES_POLICY_VERSION)
        self.assertIn('predates the current ADD-ONLY Postcodes policy', output.getvalue())
        self.assertIn('Re-validating the existing snapshot', output.getvalue())

    def test_activation_adds_only_new_rows_and_preserves_existing_rows(self):
        Suburb.objects.create(
            suburb_name='ACTON', state='ACT', postcode='2601', normalized_key='ACTACTON'
        )
        Suburb.objects.create(
            suburb_name='LEGACY PLACE', state='SA', postcode='5000', normalized_key='SALEGACY PLACE'
        )
        external_file = self._validated_snapshot()
        summary = activate_postcodes_file(external_file)
        self.assertEqual(summary['created_count'], 2)
        self.assertEqual(summary['existing_confirmed_in_current_source'], 1)
        self.assertEqual(summary['existing_not_in_current_source_preserved'], 1)
        self.assertEqual(summary['updated_count'], 0)
        self.assertEqual(summary['deleted_count'], 0)
        self.assertTrue(Suburb.objects.filter(suburb_name='LEGACY PLACE', state='SA', postcode='5000').exists())
        self.assertTrue(Suburb.objects.filter(suburb_name='BURONGA', state='NSW', postcode='2739').exists())
        self.assertTrue(Suburb.objects.filter(suburb_name='ALICE SPRINGS', state='NT', postcode='0870').exists())
        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'ACTIVE')

    def test_activation_records_ftp_origin_for_created_rows(self):
        external_file = self._validated_snapshot()
        summary = activate_postcodes_file(external_file)
        self.assertEqual(summary['created_count'], 3)
        self.assertEqual({row['origin'] for row in summary['created_rows']}, {'FTP_POSTCODES'})
        self.assertIn('Excel SUBURBS worksheet', summary['existing_master_origin_note'])
        external_file.refresh_from_db()
        self.assertEqual(external_file.import_summary['created_rows_origin'], 'FTP_POSTCODES')

    def test_active_snapshot_cannot_be_activated_again(self):
        external_file = self._validated_snapshot()
        activate_postcodes_file(external_file)
        external_file.refresh_from_db()
        with self.assertRaisesMessage(PostcodesImportError, 'Validate the postcodes file before activation'):
            activate_postcodes_file(external_file)

    def test_activation_command_requires_prior_validation(self):
        source = self._source_path()
        source.write_bytes(VALID)
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            with self.assertRaises(CommandError):
                call_command('activate_uploaded_postcodes', '--client', 'STH', stdout=StringIO())
        external_file = ExternalDataFile.objects.get(file_type='SUBURBS')
        self.assertEqual(external_file.status, 'UPLOADED')
        self.assertEqual(Suburb.objects.count(), 0)

    def test_rollback_removes_only_rows_created_by_activation(self):
        Suburb.objects.create(
            suburb_name='ACTON', state='ACT', postcode='2601', normalized_key='ACTACTON'
        )
        Suburb.objects.create(
            suburb_name='LEGACY PLACE', state='SA', postcode='5000', normalized_key='SALEGACY PLACE'
        )
        external_file = self._validated_snapshot()
        activate_postcodes_file(external_file)
        external_file.refresh_from_db()
        summary = rollback_postcodes_file(external_file, reason='Test rollback')
        self.assertEqual(summary['created_rows_removed'], 2)
        self.assertEqual(summary['historical_rows_deleted'], 0)
        self.assertTrue(Suburb.objects.filter(suburb_name='ACTON', state='ACT', postcode='2601').exists())
        self.assertTrue(Suburb.objects.filter(suburb_name='LEGACY PLACE', state='SA', postcode='5000').exists())
        self.assertFalse(Suburb.objects.filter(suburb_name='BURONGA', state='NSW', postcode='2739').exists())
        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'ROLLED_BACK')

    def test_rollback_requires_reason(self):
        external_file = self._validated_snapshot()
        activate_postcodes_file(external_file)
        external_file.refresh_from_db()
        with self.assertRaisesMessage(PostcodesImportError, 'rollback reason is required'):
            rollback_postcodes_file(external_file, reason='')

    def test_rollback_blocks_if_created_row_is_now_referenced_by_freightzone(self):
        content = b'index,suburb,state,postcode\nNEW PLACESA5001,NEW PLACE,SA,5001\n'
        external_file = self._validated_snapshot(content)
        activate_postcodes_file(external_file)
        external_file.refresh_from_db()
        FreightZone.objects.create(
            client=self.client_obj,
            carrier_service=self.carrier_service,
            suburb='NEW PLACE',
            state='SA',
            postcode='5001',
            zone='ADL',
        )
        with self.assertRaisesMessage(PostcodesImportError, 'Rollback blocked'):
            rollback_postcodes_file(external_file, reason='Should be blocked')
        self.assertTrue(Suburb.objects.filter(suburb_name='NEW PLACE', state='SA', postcode='5001').exists())
        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'ACTIVE')

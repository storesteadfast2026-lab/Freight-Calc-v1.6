from io import StringIO
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.carriers.models import Carrier, CarrierService, ClientCarrierConfig
from apps.clients.models import Client
from apps.imports.models import ExternalDataFile
from apps.imports.services.zones import (
    ZonesImportError,
    parse_zones_rows,
    snapshot_ftp_zones_file,
    validate_zones_file,
)
from apps.locations.models import Suburb
from apps.rates.models import FreightRate, FreightZone


VALID = b'''index,index2,carrier,suburb,state,postcode,zone,subzone,area\nTESTACTONACT,TESTCBR,TEST,ACTON,ACT,2601,CBR,,\nTESTBURONGANSW,TESTNSW9,TEST,BURONGA,NSW,2739,NSW9,,\n'''


class FTPZonesImportTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.client_obj = Client.objects.create(code='STH', name='Stenhoj Australia', active=True)
        self.carrier = Carrier.objects.create(code='TEST', name='Test Carrier', active=True)
        self.service = CarrierService.objects.create(
            carrier=self.carrier, service_code='ROAD', service_name='Road', active=True
        )
        ClientCarrierConfig.objects.create(
            client=self.client_obj,
            carrier_service=self.service,
            ratecard='1',
            zone_enabled=True,
            active=True,
        )

    def _snapshot(self, content=VALID):
        source = Path(self.media_dir.name) / 'zones.csv'
        source.write_bytes(content)
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            return snapshot_ftp_zones_file(client=self.client_obj, filename='zones.csv')

    def test_schema_and_index_contracts(self):
        rows, notes = parse_zones_rows(VALID)
        self.assertEqual(len(rows), 2)
        self.assertEqual(notes['duplicate_preview'], [])
        self.assertEqual(rows[0]['carrier'], 'TEST')
        self.assertEqual(rows[0]['postcode'], '2601')

    def test_missing_column_is_rejected(self):
        content = b'index,index2,carrier,suburb,state,postcode,zone,subzone\nTESTACTONACT,TESTCBR,TEST,ACTON,ACT,2601,CBR,\n'
        with self.assertRaisesMessage(ZonesImportError, 'missing required column'):
            parse_zones_rows(content)

    def test_index_mismatch_is_rejected(self):
        content = b'index,index2,carrier,suburb,state,postcode,zone,subzone,area\nWRONG,TESTCBR,TEST,ACTON,ACT,2601,CBR,,\n'
        with self.assertRaisesMessage(ZonesImportError, 'index mismatch'):
            parse_zones_rows(content)

    def test_exact_duplicate_is_reported_and_deduped_for_validation(self):
        content = VALID + b'TESTACTONACT,TESTCBR,TEST,ACTON,ACT,2601,CBR,,\n'
        rows, notes = parse_zones_rows(content)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(notes['duplicate_preview']), 1)

    def test_short_australian_postcode_is_review_only_and_not_padded(self):
        content = b'index,index2,carrier,suburb,state,postcode,zone,subzone,area\nTESTDARWINNT,TESTDRW,TEST,DARWIN,NT,800,DRW,,\n'
        Suburb.objects.create(suburb_name='DARWIN', state='NT', postcode='0800', normalized_key='NTDARWIN')
        FreightRate.objects.create(client=self.client_obj, carrier_service=self.service, zone='DRW', freight_type='P')
        external_file, _ = self._snapshot(content)
        summary = validate_zones_file(external_file)
        self.assertEqual(summary['review_postcode_format'], 1)
        row = summary['delta_preview'][0]
        self.assertEqual(row['postcode'], '800')
        self.assertEqual(row['decision'], 'REVIEW_POSTCODE_FORMAT')
        self.assertEqual(FreightZone.objects.count(), 0)

    def test_missing_suburb_reference_is_review_only(self):
        FreightRate.objects.create(client=self.client_obj, carrier_service=self.service, zone='NSW9', freight_type='P')
        external_file, _ = self._snapshot()
        summary = validate_zones_file(external_file)
        buronga = [row for row in summary['delta_preview'] if row['suburb'] == 'BURONGA'][0]
        self.assertEqual(buronga['decision'], 'REVIEW_SUBURB_REFERENCE')
        self.assertEqual(FreightZone.objects.count(), 0)

    def test_exact_existing_and_safe_add_candidate_are_distinguished(self):
        Suburb.objects.create(suburb_name='ACTON', state='ACT', postcode='2601', normalized_key='ACTACTON')
        Suburb.objects.create(suburb_name='BURONGA', state='NSW', postcode='2739', normalized_key='NSWBURONGA')
        FreightRate.objects.create(client=self.client_obj, carrier_service=self.service, zone='CBR', freight_type='P')
        FreightRate.objects.create(client=self.client_obj, carrier_service=self.service, zone='NSW9', freight_type='P')
        FreightZone.objects.create(
            client=self.client_obj, carrier_service=self.service,
            suburb='ACTON', state='ACT', postcode='2601', zone='CBR'
        )
        before = list(FreightZone.objects.values_list('suburb', 'state', 'postcode', 'zone'))
        external_file, _ = self._snapshot()
        summary = validate_zones_file(external_file)
        after = list(FreightZone.objects.values_list('suburb', 'state', 'postcode', 'zone'))
        self.assertEqual(before, after)
        self.assertEqual(summary['exact_matches'], 1)
        self.assertEqual(summary['candidate_add'], 1)
        self.assertFalse(summary['database_updated'])

    def test_ambiguous_service_mapping_is_review_only(self):
        second = CarrierService.objects.create(carrier=self.carrier, service_code='GENERAL', service_name='General', active=True)
        config = ClientCarrierConfig.objects.get(client=self.client_obj, carrier_service=self.service)
        config.zone_enabled = False
        config.save(update_fields=['zone_enabled'])
        ClientCarrierConfig.objects.create(
            client=self.client_obj, carrier_service=second, ratecard='2', zone_enabled=False, active=True
        )
        external_file, _ = self._snapshot()
        summary = validate_zones_file(external_file)
        self.assertEqual(summary['review_service_mapping'], 2)
        self.assertEqual(FreightZone.objects.count(), 0)

    def test_snapshot_is_idempotent_and_source_is_preserved(self):
        source = Path(self.media_dir.name) / 'zones.csv'
        source.write_bytes(VALID)
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            first, created_first = snapshot_ftp_zones_file(client=self.client_obj)
            second, created_second = snapshot_ftp_zones_file(client=self.client_obj)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertTrue(source.exists())
        self.assertNotEqual(Path(first.uploaded_file.path).resolve(), source.resolve())

    def test_command_is_validation_only_and_reuses_summary(self):
        source = Path(self.media_dir.name) / 'zones.csv'
        source.write_bytes(VALID)
        first_output = StringIO()
        second_output = StringIO()
        with override_settings(FTP_UPLOADED_DATA_DIR=self.media_dir.name):
            call_command('process_uploaded_zones', '--client', 'STH', stdout=first_output)
            call_command('process_uploaded_zones', '--client', 'STH', stdout=second_output)
        self.assertEqual(FreightZone.objects.count(), 0)
        external_file = ExternalDataFile.objects.get(file_type='ZONES', source_method='FTP_DROP')
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertIn('NO FREIGHT ZONES WERE ADDED', first_output.getvalue())
        self.assertIn('Reusing the existing Zones validation summary', second_output.getvalue())

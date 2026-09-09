from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from apps.audit.models import AuditEvent
from apps.clients.models import Client
from apps.imports.models import ExternalDataFile, ProductSourceRow, StockSourceRow
from apps.imports.services.ftp_inbox import inspect_ftp_inbox, scan_ftp_inbox
from apps.locations.models import Suburb


class FtpInboxTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            code='STH',
            name='Stenhoj Australia',
            active=True,
        )
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'uploaded_data'
        self.media = Path(self.temp.name) / 'media'
        self.root.mkdir()
        self.media.mkdir()
        self.settings_override = override_settings(
            FTP_UPLOADED_DATA_DIR=str(self.root),
            MEDIA_ROOT=str(self.media),
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def _write(self, filename: str, content: bytes):
        (self.root / filename).write_bytes(content)

    def test_inspection_is_read_only(self):
        self._write('products.csv', b'sku,name\nA1,Test\n')
        before = ExternalDataFile.objects.count()
        result = inspect_ftp_inbox()
        self.assertTrue(result['root_exists'])
        self.assertEqual(len(result['recognised']), 1)
        self.assertEqual(result['recognised'][0]['file_type'], 'PRODUCTS')
        self.assertEqual(ExternalDataFile.objects.count(), before)

    def test_scan_registers_known_files_without_operational_import(self):
        self._write('products.csv', b'sku,name\nA1,Test\n')
        self._write('postcodes.csv', b'index,suburb,state,postcode\n1,TEST,SA,5000\n')
        suburb_before = Suburb.objects.count()

        summary = scan_ftp_inbox(client=self.client_obj)

        self.assertEqual(summary['recognised'], 2)
        self.assertEqual(summary['new_snapshots'], 2)
        self.assertEqual(summary['errors'], 0)
        self.assertEqual(
            ExternalDataFile.objects.get(file_type='PRODUCTS').source_method,
            'FTP_DROP',
        )
        self.assertEqual(
            ExternalDataFile.objects.get(file_type='SUBURBS').source_method,
            'FTP_DROP',
        )
        self.assertEqual(ProductSourceRow.objects.count(), 0)
        self.assertEqual(StockSourceRow.objects.count(), 0)
        self.assertEqual(Suburb.objects.count(), suburb_before)

    def test_second_scan_is_idempotent_by_sha(self):
        self._write('fuel.csv', b'rate_no,carrier,name,surcharge,type\n1,TNT,Fuel,10,PRICE\n')
        first = scan_ftp_inbox(client=self.client_obj)
        second = scan_ftp_inbox(client=self.client_obj)
        self.assertEqual(first['new_snapshots'], 1)
        self.assertEqual(second['new_snapshots'], 0)
        self.assertEqual(second['unchanged'], 1)
        self.assertEqual(
            ExternalDataFile.objects.filter(
                file_type='FUEL',
                source_method='FTP_DROP',
            ).count(),
            1,
        )

    def test_changed_content_creates_new_version(self):
        self._write('zones.csv', b'carrier,suburb,zone\nTNT,A,Z1\n')
        scan_ftp_inbox(client=self.client_obj)
        self._write('zones.csv', b'carrier,suburb,zone\nTNT,A,Z2\n')
        second = scan_ftp_inbox(client=self.client_obj)
        self.assertEqual(second['new_snapshots'], 1)
        self.assertEqual(
            ExternalDataFile.objects.filter(
                file_type='ZONES',
                source_method='FTP_DROP',
            ).count(),
            2,
        )

    def test_empty_known_file_is_reported_and_not_registered(self):
        self._write('stock.csv', b'')
        result = scan_ftp_inbox(client=self.client_obj)
        self.assertEqual(result['recognised'], 1)
        self.assertEqual(result['errors'], 1)
        self.assertFalse(ExternalDataFile.objects.filter(file_type='STOCK').exists())

    def test_unknown_files_are_ignored(self):
        self._write('notes.txt', b'not an import')
        result = scan_ftp_inbox(client=self.client_obj)
        self.assertEqual(result['recognised'], 0)
        self.assertEqual(result['new_snapshots'], 0)
        self.assertEqual(result['ignored'], 1)

    def test_scan_creates_audit_events(self):
        self._write('products.csv', b'sku,name\nA1,Test\n')
        scan_ftp_inbox(client=self.client_obj)
        self.assertTrue(
            AuditEvent.objects.filter(
                client=self.client_obj,
                event_type='FTP_INBOX_CHECKED',
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                client=self.client_obj,
                event_type='FTP_INBOX_FILE_REGISTERED',
            ).exists()
        )

    def test_scan_returns_visual_feedback_metadata(self):
        self._write('products.csv', b'sku,name\nA1,Test\n')
        result = scan_ftp_inbox(client=self.client_obj)

        self.assertTrue(result['checked_at_display'])
        self.assertEqual(len(result['files']), 1)
        item = result['files'][0]
        self.assertEqual(item['filename'], 'products.csv')
        self.assertEqual(item['result_label'], 'NEW VERSION')
        self.assertTrue(item['sha_checked'])
        self.assertTrue(item['source_modified_at_display'])
        self.assertTrue(item['size_display'])
        self.assertIn('Snapshot #', item['action_label'])

    def test_unchanged_visual_feedback_says_no_action_required(self):
        self._write('postcodes.csv', b'index,suburb,state,postcode\n1,TEST,SA,5000\n')
        scan_ftp_inbox(client=self.client_obj)
        result = scan_ftp_inbox(client=self.client_obj)

        item = result['files'][0]
        self.assertEqual(item['result_label'], 'UNCHANGED')
        self.assertEqual(item['action_label'], 'No action required')
        self.assertTrue(item['sha_checked'])
        self.assertIsNotNone(item['matching_snapshot_id'])

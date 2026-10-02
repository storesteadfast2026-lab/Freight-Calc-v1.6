"""Read-only continuity export uses the same Product Master comparison rules."""

import io
import json
from hashlib import sha256
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.clients.models import Client, Customer
from apps.imports.models import ProductMaster
from apps.imports.management.commands.export_continuity_state import safe_filename
from apps.imports.tests import test_product_master_reconciliation_bridge as bridge_tests
from apps.products.models import Product


class ContinuityStateTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.sth = Client.objects.create(code='STH', name='Steadfast')
        self.pon = Client.objects.create(code='PON', name='Pon Bike')
        Customer.objects.create(code='STH', name='Steadfast', linked_client=self.sth,
                                source_row_number=1)
        Customer.objects.create(code='PON', name='Pon Bike', linked_client=self.pon,
                                source_row_number=2)
        Product.objects.create(client=self.sth, sku='A1', name='Existing STH')
        Product.objects.create(client=self.pon, sku='A1', name='Existing PON')
        data = b'continuity test workbook'
        self.master = ProductMaster(
            original_filename='products.xls', sha256=sha256(data).hexdigest(),
            file_size_bytes=len(data), status='VALIDATED',
            validation_summary={'customer_counts': {'STH': 4, 'PON': 1}},
        )
        self.master.original_file.save('products.xls', ContentFile(data), save=False)
        self.master.save()

    def export(self):
        output = io.StringIO()
        call_command('export_continuity_state', stdout=output)
        return json.loads(output.getvalue())

    def test_live_aggregates_exclusions_and_no_database_writes(self):
        with patch('apps.imports.services.product_master.read_product_file',
                   side_effect=bridge_tests.ProductMasterReadOnlyBridgeTests.import_workbook):
            with CaptureQueriesContext(connection) as queries:
                state = self.export()
        self.assertFalse([q['sql'] for q in queries if q['sql'].lstrip().upper().startswith(
            ('INSERT ', 'UPDATE ', 'DELETE '))])
        self.assertEqual(state['counts']['products'], 2)
        self.assertEqual(state['migrations_pending'], [])
        self.assertEqual(state['active_product_master']['sha256'], self.master.sha256)
        sth = next(row for row in state['products_by_calculator_customer']
                   if row['calculator_customer'] == 'STH')
        self.assertEqual((sth['source_only'], sth['eligible_remaining'], sth['blocked'],
                          sth['invalid_rows']), (2, 1, 1, 1))
        self.assertEqual(sth['operational_products'], sth['active'] + sth['inactive'])
        Product.objects.create(client=self.sth, sku='NEW', name='Operational import')
        with patch('apps.imports.services.product_master.read_product_file',
                   side_effect=bridge_tests.ProductMasterReadOnlyBridgeTests.import_workbook):
            refreshed = self.export()
        sth = next(row for row in refreshed['products_by_calculator_customer']
                   if row['calculator_customer'] == 'STH')
        self.assertEqual((sth['source_only'], sth['eligible_remaining'], sth['blocked'],
                          sth['operational_products']), (1, 0, 1, 2))

    def test_checksum_mismatch_fails_without_declaring_state(self):
        self.master.sha256 = '0' * 64
        self.master.save(update_fields=['sha256'])
        output = io.StringIO()
        with self.assertRaisesMessage(CommandError, 'file checksum differs'):
            call_command('export_continuity_state', stdout=output)
        self.assertEqual(output.getvalue(), '')

    def test_source_names_do_not_expose_url_credentials_or_tokens(self):
        self.assertEqual(safe_filename('https://user:pass@example.test/a.xls?token=secret'), 'a.xls')
        self.assertEqual(safe_filename(r'C:\source\password=real.xls'), '[redacted filename]')

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import xlrd
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.clients.customer_import import (
    CustomerImportError, import_customers, preview_customers,
)
from apps.clients.models import Client, Customer, CustomerImport


HEADER = ('code', 'name', 'group', 'group1', 'group2', 'their_code', 'wh_pick_code',
          'acn', 'abn', 'gst_code', 'sett_days', 'paydays_type', 'date', 'user')
XLS_CONTENT = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1test-customer-fixture'


def source_rows(count=111):
    codes = ['*', 'STH', 'ABC'] + [f'C{i:03}' for i in range(count - 3)]
    return [[code, 'All Customers' if code == '*' else f'Customer {code}',
             'XXX' if code == '*' else '', 'AC01', 'NOREP', '', 'WLOC06F',
             '00123456', '00123456789', 'GST', 14.0, 'Days', 38442.0, 'LDU']
            for code in codes]


class FakeSheet:
    ncols = 14

    def __init__(self, rows):
        self.rows = [list(HEADER)] + rows
        self.nrows = len(self.rows)

    def cell_value(self, row, column):
        return self.rows[row][column]

    def cell(self, row, column):
        value = self.cell_value(row, column)
        if row and column == 12:
            cell_type = xlrd.XL_CELL_DATE
        elif isinstance(value, float):
            cell_type = xlrd.XL_CELL_NUMBER
        else:
            cell_type = xlrd.XL_CELL_TEXT
        return SimpleNamespace(value=value, ctype=cell_type)


def fake_book(rows):
    sheet = FakeSheet(rows)
    return SimpleNamespace(nsheets=1, datemode=0, sheet_by_index=lambda index: sheet)


class CustomerImportTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        setting = override_settings(MEDIA_ROOT=self.temp.name)
        setting.enable()
        self.addCleanup(setting.disable)
        self.rows = source_rows()
        reader = patch('apps.clients.customer_import.xlrd.open_workbook',
                       side_effect=lambda **kwargs: fake_book(self.rows))
        reader.start()
        self.addCleanup(reader.stop)
        self.sth = Client.objects.create(code='STH', name='STH')
        self.temp_client = Client.objects.create(code='TEMP', name='Temporary')
        self.temp2_client = Client.objects.create(code='temp2', name='Temporary 2')

    def test_realistic_111_row_import_and_repeat_are_idempotent(self):
        preview = preview_customers(XLS_CONTENT)
        self.assertEqual((preview.total_rows, len(preview.new), len(preview.special)), (111, 111, 1))
        self.assertEqual((Customer.objects.count(), CustomerImport.objects.count()), (0, 0))
        first = import_customers(XLS_CONTENT, filename='customers.xls')
        self.assertEqual((first.created_count, first.updated_count), (111, 0))
        self.assertEqual((Client.objects.count(), Customer.objects.count()), (3, 111))
        sth = Customer.objects.get(code='STH')
        self.assertEqual(sth.linked_client, self.sth)
        self.assertEqual(sth.source_row_number, 3)
        self.assertEqual(sth.raw_data['acn'], '00123456')
        self.assertEqual(sth.source_date.isoformat(), '2005-03-31')
        self.assertTrue(Customer.objects.get(code='*').is_special)
        self.assertIsNone(Customer.objects.get(code='*').linked_client)
        second = import_customers(XLS_CONTENT, filename='customers.xls')
        self.assertEqual((second.created_count, second.updated_count, second.unchanged_count), (0, 0, 111))
        self.assertEqual(CustomerImport.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(event_type='CUSTOMER_MASTER_IMPORTED').count(), 2)
        self.assertTrue(Path(second.source_file.path).exists())
        self.assertEqual(list(Client.objects.values_list('code', flat=True)), ['STH', 'TEMP', 'temp2'])

    def test_change_and_missing_are_reported_not_deleted(self):
        import_customers(XLS_CONTENT, filename='customers.xls')
        self.rows[2][1] = 'Updated name'
        self.rows.pop()
        preview = preview_customers(XLS_CONTENT)
        self.assertEqual((len(preview.changed), len(preview.missing)), (1, 1))
        history = import_customers(XLS_CONTENT, filename='customers.xls')
        self.assertEqual((history.created_count, history.updated_count, history.missing_count), (0, 1, 1))
        self.assertEqual(Customer.objects.count(), 111)
        self.assertEqual(Customer.objects.get(code='ABC').name, 'Updated name')

    def test_invalid_blank_and_duplicate_codes_block_import(self):
        self.rows[2][0] = ''
        self.rows[3][1] = ''
        self.rows[4][0] = 'STH'
        preview = preview_customers(XLS_CONTENT)
        self.assertEqual((len(preview.errors), len(preview.duplicates)), (2, 1))
        with self.assertRaises(CustomerImportError):
            import_customers(XLS_CONTENT, filename='customers.xls')
        self.assertEqual(Customer.objects.count(), 0)

    def test_preview_state_change_requires_new_validation(self):
        from apps.clients.customer_import import master_state_digest
        snapshot = master_state_digest()
        Client.objects.create(code='PON', name='New Calculator Customer')
        with self.assertRaisesRegex(CustomerImportError, 'changed after preview'):
            import_customers(XLS_CONTENT, filename='customers.xls', expected_state=snapshot)

    def test_admin_upload_preview_and_confirmation(self):
        user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'secret')
        self.client.force_login(user)
        url = reverse('admin:clients_customer_import')
        response = self.client.post(url, {'action': 'validate', 'file': SimpleUploadedFile('customers.xls', XLS_CONTENT)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((Customer.objects.count(), CustomerImport.objects.count(), AuditEvent.objects.count()), (0, 0, 0))
        self.assertContains(response, 'Customer import preview')
        token = response.context['token']
        response = self.client.post(url, {'action': 'import', 'token': token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual((Customer.objects.count(), CustomerImport.objects.count()), (111, 1))

    def test_non_admin_user_cannot_request_import(self):
        user = get_user_model().objects.create_user('customer', password='secret')
        self.client.force_login(user)
        response = self.client.get(reverse('admin:clients_customer_import'))
        self.assertNotEqual(response.status_code, 200)

    def test_preview_rejects_state_change_before_admin_confirmation(self):
        user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'secret')
        self.client.force_login(user)
        url = reverse('admin:clients_customer_import')
        response = self.client.post(url, {
            'action': 'validate', 'file': SimpleUploadedFile('customers.xls', XLS_CONTENT),
        })
        Client.objects.create(code='PON', name='Later change')
        response = self.client.post(url, {'action': 'import', 'token': response.context['token']})
        self.assertContains(response, 'Validate the file again')
        self.assertFalse(Customer.objects.exists())

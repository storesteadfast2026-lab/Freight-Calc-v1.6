from unittest import TestCase
from unittest.mock import patch

from apps.imports.services.product_file_adapters import (
    PRODUCT_SOURCE_EXTENSIONS,
    read_product_file,
)
from apps.imports.services.xlsx_reader import SourceImportError


PRODUCT_ALIASES = {
    'code': ('code', 'product code', 'product_code', 'sku'),
    'name': ('name', 'product name', 'product_name'),
    'description': ('description', 'product description', 'product_description'),
    'category': ('category', 'product category', 'product_category'),
    'length': ('length', 'length mm', 'length_mm'),
    'width': ('width', 'width mm', 'width_mm'),
    'height': ('height', 'height mm', 'height_mm'),
    'cubic': ('cubic', 'cubic m3', 'cubic_m3', 'volume'),
    'quantity': ('quantity', 'qty'),
    'weight': ('weight', 'weight kg', 'weight_kg'),
    'pallet': ('pallet', 'pallets', 'pallet quantity'),
    'comment': ('comment', 'comments', 'notes'),
    'status': ('status', 'product status', 'product_status'),
}


class FakeSheet:
    name = 'products'

    def __init__(self):
        self.rows = [
            [
                'code', 'name', 'description', 'category', 'length', 'width',
                'height', 'cubic', 'quantity', 'weight', 'pallet', 'comment',
                'status', 'outer_l', 'outer_w', 'outer_h', 'inner_l', 'inner_w',
                'inner_h', 'piece_l', 'piece_w', 'piece_h',
            ],
            [
                'XLS-1', 'Legacy product', '', 'TEST', 100, 200, 300, 0.006,
                1, 10, 2, '', 'L', 110, 210, 310, 0, 0, 0, 0, 0, 0,
            ],
        ]
        self.nrows = len(self.rows)

    def row_values(self, row_index):
        return list(self.rows[row_index])


class FakeWorkbook:
    def __init__(self):
        self.sheet = FakeSheet()
        self.released = False

    def sheets(self):
        return [self.sheet]

    def release_resources(self):
        self.released = True


class ProductFileAdapterTests(TestCase):
    def read(self, content, filename):
        return read_product_file(
            content,
            filename,
            aliases=PRODUCT_ALIASES,
            required_fields=tuple(PRODUCT_ALIASES),
            expected_csv_column_count=13,
        )

    def test_registered_formats_are_isolated_from_the_import_workflow(self):
        self.assertEqual(PRODUCT_SOURCE_EXTENSIONS, ('.xls', '.csv', '.xlsx'))

    def test_csv_reader_returns_the_canonical_result(self):
        content = (
            'code,name,description,category,length,width,height,cubic,quantity,'
            'weight,pallet,comment,status\r\n'
            'CSV-1,Product,,TEST,100,200,300,0.006,1,10,0,,L\r\n'
        ).encode('cp1252')

        result = self.read(content, 'products.csv')

        self.assertEqual(result.source_format, 'CSV')
        self.assertEqual(result.source_column_count, 13)
        self.assertEqual(result.records[0]['code'], 'CSV-1')
        self.assertEqual(result.rejected_rows, [])

    def test_xls_reader_keeps_extra_source_columns_in_raw_data(self):
        workbook = FakeWorkbook()
        content = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1test'
        with patch(
            'apps.imports.services.product_file_adapters.adapter._open_legacy_xls',
            return_value=workbook,
        ):
            result = self.read(content, 'products.xls')

        self.assertEqual(result.source_format, 'XLS')
        self.assertEqual(result.source_column_count, 22)
        self.assertEqual(result.records[0]['code'], 'XLS-1')
        self.assertEqual(result.records[0]['pallet'], 2)
        self.assertEqual(result.records[0]['_raw_data']['outer_l'], 110)
        self.assertTrue(workbook.released)

    def test_extension_and_content_must_match(self):
        content = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1test'
        with self.assertRaisesRegex(SourceImportError, 'extension indicates CSV'):
            self.read(content, 'products.csv')

    def test_unregistered_xml_is_rejected_at_the_adapter_boundary(self):
        with self.assertRaisesRegex(SourceImportError, 'Unsupported Product source format'):
            self.read(b'<products/>', 'products.xml')

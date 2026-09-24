from __future__ import annotations

import io
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import xlrd
from xlrd import sheet as xlrd_sheet

from apps.imports.services.xlsx_reader import (
    SourceImportError,
    json_safe_value,
    normalize_header,
    read_csv_records,
    read_xlsx_records,
    value_to_text,
)


OLE_COMPOUND_SIGNATURE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
ZIP_SIGNATURES = (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')


@dataclass(frozen=True)
class ProductFileReadResult:
    """Canonical output consumed by the Product staging workflow."""

    source_format: str
    worksheet: str
    header_row: int
    headers: list[str]
    records: list[dict[str, Any]]
    rejected_rows: list[dict[str, Any]] = field(default_factory=list)
    encoding: str = ''
    warnings: list[str] = field(default_factory=list)

    @property
    def source_column_count(self) -> int:
        return len(self.headers)


class ProductFileReader(Protocol):
    format_name: str
    extensions: tuple[str, ...]

    def read(
        self,
        content: bytes,
        *,
        aliases: dict[str, tuple[str, ...]],
        required_fields: tuple[str, ...],
        expected_csv_column_count: int,
    ) -> ProductFileReadResult: ...


class CsvProductFileReader:
    format_name = 'CSV'
    extensions = ('.csv',)

    def read(self, content, *, aliases, required_fields, expected_csv_column_count):
        worksheet, header_row, headers, records, rejected, encoding = read_csv_records(
            content,
            aliases=aliases,
            required_fields=required_fields,
            expected_column_count=expected_csv_column_count,
        )
        return ProductFileReadResult(
            source_format=self.format_name,
            worksheet=worksheet,
            header_row=header_row,
            headers=headers,
            records=records,
            rejected_rows=rejected,
            encoding=encoding,
        )


class XlsxProductFileReader:
    format_name = 'XLSX'
    extensions = ('.xlsx',)

    def read(self, content, *, aliases, required_fields, expected_csv_column_count):
        worksheet, header_row, headers, records = read_xlsx_records(
            content,
            preferred_sheet_names=('products', 'product_sth', 'product'),
            aliases=aliases,
            required_fields=required_fields,
        )
        return ProductFileReadResult(
            source_format=self.format_name,
            worksheet=worksheet,
            header_row=header_row,
            headers=headers,
            records=records,
        )


_XLRD_OPEN_LOCK = threading.RLock()


def _open_legacy_xls(content: bytes):
    """Open the Translogic legacy workbook without truncating rows.

    The current Translogic export identifies itself as an older BIFF workbook,
    whose declared row limit is 16,384, while it legitimately contains more
    rows.  xlrd otherwise stops at that declared limit.  The temporary patch is
    protected by a process lock and is restored before this function returns.
    It changes only the reader's safety ceiling; it does not alter source data.
    """

    log = io.StringIO()
    with _XLRD_OPEN_LOCK:
        original_init = xlrd_sheet.Sheet.__init__

        def expanded_row_limit(sheet, *args, **kwargs):
            original_init(sheet, *args, **kwargs)
            sheet.utter_max_rows = max(sheet.utter_max_rows, 65536)

        xlrd_sheet.Sheet.__init__ = expanded_row_limit
        try:
            return xlrd.open_workbook(
                file_contents=content,
                on_demand=False,
                formatting_info=False,
                ragged_rows=False,
                encoding_override='cp1252',
                ignore_workbook_corruption=True,
                logfile=log,
            )
        except (xlrd.XLRDError, OSError, ValueError, IndexError, AssertionError) as exc:
            raise SourceImportError(
                f'The uploaded file is not a readable legacy .xls workbook: {exc}'
            ) from exc
        finally:
            xlrd_sheet.Sheet.__init__ = original_init


def _aliases_by_normalized_name(aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for logical_name, values in aliases.items():
        for value in values:
            output[normalize_header(value)] = logical_name
    return output


def _header_mapping(values: list[Any], aliases: dict[str, tuple[str, ...]]) -> dict[str, int]:
    lookup = _aliases_by_normalized_name(aliases)
    mapping: dict[str, int] = {}
    for index, value in enumerate(values):
        logical_name = lookup.get(normalize_header(value))
        if logical_name and logical_name not in mapping:
            mapping[logical_name] = index
    return mapping


class XlsProductFileReader:
    format_name = 'XLS'
    extensions = ('.xls',)

    def read(self, content, *, aliases, required_fields, expected_csv_column_count):
        if not content:
            raise SourceImportError('The uploaded Excel file is empty.')

        workbook = _open_legacy_xls(content)
        try:
            preferred = {
                normalize_header(name)
                for name in ('products', 'product_sth', 'product')
            }
            sheets = sorted(
                workbook.sheets(),
                key=lambda sheet: 0 if normalize_header(sheet.name) in preferred else 1,
            )

            selected = None
            for sheet in sheets:
                for row_index in range(min(25, sheet.nrows)):
                    values = sheet.row_values(row_index)
                    mapping = _header_mapping(values, aliases)
                    if all(field in mapping for field in required_fields):
                        selected = (sheet, row_index, values, mapping)
                        break
                if selected:
                    break

            if selected is None:
                expected = ', '.join(required_fields)
                raise SourceImportError(
                    'Could not find a worksheet/header row with the required columns. '
                    f'Expected logical fields: {expected}.'
                )

            sheet, header_index, header_values, mapping = selected
            headers = [
                value_to_text(value) or f'column_{index + 1}'
                for index, value in enumerate(header_values)
            ]
            records: list[dict[str, Any]] = []

            for row_index in range(header_index + 1, sheet.nrows):
                values = sheet.row_values(row_index)
                if not any(value not in (None, '') for value in values):
                    continue
                record = {
                    logical_name: values[column_index] if column_index < len(values) else None
                    for logical_name, column_index in mapping.items()
                }
                record['_row_number'] = row_index + 1
                record['_raw_data'] = {
                    headers[index]: json_safe_value(value)
                    for index, value in enumerate(values[:len(headers)])
                    if value not in (None, '')
                }
                records.append(record)

            if not records:
                raise SourceImportError('The workbook contains headers but no data rows.')
            return ProductFileReadResult(
                source_format=self.format_name,
                worksheet=sheet.name,
                header_row=header_index + 1,
                headers=headers,
                records=records,
                warnings=(
                    ['Legacy XLS compatibility mode was used for this source.']
                    if sheet.nrows > 16384
                    else []
                ),
            )
        finally:
            workbook.release_resources()


READERS: tuple[ProductFileReader, ...] = (
    XlsProductFileReader(),
    CsvProductFileReader(),
    XlsxProductFileReader(),
)
PRODUCT_SOURCE_EXTENSIONS = tuple(
    extension
    for reader in READERS
    for extension in reader.extensions
)


def _content_format(content: bytes) -> str:
    if content.startswith(OLE_COMPOUND_SIGNATURE):
        return 'XLS'
    if content.startswith(ZIP_SIGNATURES):
        return 'XLSX'
    stripped = content.lstrip()
    if stripped.startswith(b'<'):
        return 'XML'
    return 'CSV'


def read_product_file(
    content: bytes,
    filename: str,
    *,
    aliases: dict[str, tuple[str, ...]],
    required_fields: tuple[str, ...],
    expected_csv_column_count: int,
) -> ProductFileReadResult:
    """Read one Product source through the registered format adapter."""

    suffix = Path(filename or '').suffix.lower()
    reader = next(
        (candidate for candidate in READERS if suffix in candidate.extensions),
        None,
    )
    if reader is None:
        allowed = ', '.join(PRODUCT_SOURCE_EXTENSIONS)
        raise SourceImportError(
            f'Unsupported Product source format {suffix or "(no extension)"}. '
            f'Accepted extensions: {allowed}.'
        )

    actual_format = _content_format(content)
    if actual_format != reader.format_name:
        raise SourceImportError(
            f'The filename extension indicates {reader.format_name}, but the file '
            f'content is {actual_format}. Use the correct extension or regenerate the source.'
        )

    return reader.read(
        content,
        aliases=aliases,
        required_fields=required_fields,
        expected_csv_column_count=expected_csv_column_count,
    )

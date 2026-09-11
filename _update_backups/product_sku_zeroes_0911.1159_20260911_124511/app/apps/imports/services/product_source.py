from __future__ import annotations

import hashlib
import csv
import io
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.imports.models import (
    ExternalDataFile,
    ProductSourceRejectedRow,
    ProductSourceRow,
)
from apps.imports.services.audit import create_audit_event
from apps.imports.services.xlsx_reader import (
    SourceImportError,
    calculate_sha256,
    normalize_sku,
    parse_decimal,
    read_csv_records,
    read_file_bytes,
    read_xlsx_records,
    value_to_text,
)
from apps.products.models import Product


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
PRODUCT_REQUIRED_FIELDS = tuple(PRODUCT_ALIASES)
PRODUCT_CSV_COLUMN_COUNT = 13


def _is_empty_placeholder(record: dict[str, Any]) -> bool:
    if normalize_sku(record.get('code')):
        return False
    meaningful_text = any(
        value_to_text(record.get(field)).strip()
        for field in ('name', 'description', 'category', 'comment', 'status')
    )
    numeric_values = []
    for field in ('length', 'width', 'height', 'cubic', 'quantity', 'weight', 'pallet'):
        value = record.get(field)
        if value in (None, ''):
            continue
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            return False
    return not meaningful_text and all(value == 0 for value in numeric_values)


def _parse_product_records(records: list[dict[str, Any]]):
    parsed: list[dict[str, Any]] = []
    errors: list[str] = []
    skipped_empty = 0

    for record in records:
        row_number = int(record['_row_number'])
        if _is_empty_placeholder(record):
            skipped_empty += 1
            continue

        row_errors: list[str] = []
        code_raw = value_to_text(record.get('code'))
        code_normalized = normalize_sku(record.get('code'))
        if not code_normalized:
            row_errors.append(f'Row {row_number}: product code is required.')

        parsed_row = {
            'source_row_number': row_number,
            'product_code_raw': code_raw,
            'product_code_normalized': code_normalized,
            'name': value_to_text(record.get('name')),
            'description': value_to_text(record.get('description')),
            'category': value_to_text(record.get('category')),
            'length_mm': parse_decimal(
                record.get('length'), field_label='length', row_number=row_number, errors=row_errors
            ),
            'width_mm': parse_decimal(
                record.get('width'), field_label='width', row_number=row_number, errors=row_errors
            ),
            'height_mm': parse_decimal(
                record.get('height'), field_label='height', row_number=row_number, errors=row_errors
            ),
            'cubic_m3': parse_decimal(
                record.get('cubic'), field_label='cubic', row_number=row_number, errors=row_errors
            ),
            'quantity': parse_decimal(
                record.get('quantity'), field_label='quantity', row_number=row_number, errors=row_errors
            ),
            'weight_kg': parse_decimal(
                record.get('weight'), field_label='weight', row_number=row_number, errors=row_errors
            ),
            'pallet': parse_decimal(
                record.get('pallet'), field_label='pallet', row_number=row_number, errors=row_errors
            ),
            'comment': value_to_text(record.get('comment')),
            'source_status': value_to_text(record.get('status')),
            'raw_data': record.get('_raw_data') or {},
            'validation_errors': row_errors,
        }
        parsed.append(parsed_row)
        errors.extend(row_errors)

    counts = Counter(row['product_code_normalized'] for row in parsed if row['product_code_normalized'])
    duplicate_codes = sorted(code for code, count in counts.items() if count > 1)
    for code in duplicate_codes:
        duplicate_rows = [str(row['source_row_number']) for row in parsed if row['product_code_normalized'] == code]
        errors.append(f'Duplicate product code {code} on rows {", ".join(duplicate_rows)}.')

    return parsed, errors, duplicate_codes, skipped_empty


def _dimension_status(row: dict[str, Any]) -> str:
    values = [row.get('length_mm'), row.get('width_mm'), row.get('height_mm')]
    positive = [value is not None and value > 0 for value in values]
    if all(positive):
        return 'COMPLETE'
    if not any(positive):
        return 'ZERO_OR_MISSING'
    return 'PARTIAL'


def _product_map(client) -> dict[str, Product]:
    return {
        normalize_sku(product.sku): product
        for product in Product.objects.filter(client=client)
    }


def _comparison_details(row: ProductSourceRow | dict[str, Any], product: Product | None):
    if product is None:
        return 'NEW', []

    def source_value(name):
        return getattr(row, name) if isinstance(row, ProductSourceRow) else row.get(name)

    fields = (
        ('length', source_value('length_mm'), product.length_m, Decimal('1000')),
        ('width', source_value('width_mm'), product.width_m, Decimal('1000')),
        ('height', source_value('height_mm'), product.height_m, Decimal('1000')),
        ('weight', source_value('weight_kg'), product.weight_kg, Decimal('1')),
        ('cubic', source_value('cubic_m3'), product.cubic_m3, Decimal('1')),
    )
    differences = []
    for label, source, current, divisor in fields:
        normalised_source = None if source is None else source / divisor
        if normalised_source != current:
            differences.append(label)
    return ('DIFFERENT' if differences else 'UNCHANGED'), differences


def _comparison_summary(parsed: list[dict[str, Any]], *, client) -> dict[str, Any]:
    products = _product_map(client)
    source_skus = {row['product_code_normalized'] for row in parsed}
    django_skus = set(products)
    unchanged = 0
    different = 0
    difference_counts = Counter()
    for row in parsed:
        status, differences = _comparison_details(
            row,
            products.get(row['product_code_normalized']),
        )
        if status == 'UNCHANGED':
            unchanged += 1
        elif status == 'DIFFERENT':
            different += 1
            difference_counts.update(differences)
    return {
        'source_skus': source_skus,
        'django_skus': django_skus,
        'matched': len(source_skus & django_skus),
        'unchanged': unchanged,
        'different': different,
        'difference_counts': dict(sorted(difference_counts.items())),
        'source_only': sorted(source_skus - django_skus),
        'django_only': sorted(django_skus - source_skus),
    }


def build_product_source_validation_report(external_file: ExternalDataFile) -> str:
    """Return an Excel-friendly detail CSV without changing operational data."""
    products = _product_map(external_file.client)
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow([
        'record_status', 'source_row', 'source_columns', 'sku', 'comparison',
        'different_fields', 'validation_errors', 'name', 'dimension_status',
        'source_length_mm', 'source_width_mm', 'source_height_mm',
        'source_weight_kg', 'source_cubic_m3', 'source_pallet', 'source_status',
        'current_length_m', 'current_width_m', 'current_height_m',
        'current_weight_kg', 'current_cubic_m3',
    ])
    for row in ProductSourceRow.objects.filter(external_file=external_file).iterator():
        product = products.get(row.product_code_normalized)
        comparison, differences = _comparison_details(
            row,
            product,
        )
        writer.writerow([
            'VALID', row.source_row_number, PRODUCT_CSV_COLUMN_COUNT,
            row.product_code_normalized, comparison, '|'.join(differences), '', row.name,
            _dimension_status({
                'length_mm': row.length_mm,
                'width_mm': row.width_mm,
                'height_mm': row.height_mm,
            }),
            row.length_mm, row.width_mm, row.height_mm, row.weight_kg, row.cubic_m3,
            row.pallet, row.source_status,
            product.length_m if product else '',
            product.width_m if product else '',
            product.height_m if product else '',
            product.weight_kg if product else '',
            product.cubic_m3 if product else '',
        ])
    for row in ProductSourceRejectedRow.objects.filter(external_file=external_file).iterator():
        raw = list(row.raw_values or [])
        writer.writerow([
            'REJECTED', row.source_row_number, row.column_count or '',
            raw[0] if raw else '', '', '', '|'.join(row.validation_errors or []),
            raw[1] if len(raw) > 1 else '', '', '', '', '', '', '', '', '',
            '', '', '', '', '',
        ])
    return '\ufeff' + stream.getvalue()


def validate_product_source_file(external_file: ExternalDataFile, *, actor=None, request=None) -> dict:
    if external_file.file_type != 'PRODUCTS':
        raise SourceImportError('Only PRODUCTS files can be validated by this operation.')

    request_id = hashlib.sha256(
        f'product-source:{timezone.now().isoformat()}:{external_file.pk}'.encode()
    ).hexdigest()[:32]

    try:
        content = read_file_bytes(external_file)
        calculated_hash = calculate_sha256(content)
        suffix = Path(external_file.original_filename or '').suffix.lower()
        rejected_rows: list[dict[str, Any]] = []
        encoding = ''
        if suffix == '.csv':
            sheet_name, header_row, headers, records, rejected_rows, encoding = read_csv_records(
                content,
                aliases=PRODUCT_ALIASES,
                required_fields=PRODUCT_REQUIRED_FIELDS,
                expected_column_count=PRODUCT_CSV_COLUMN_COUNT,
            )
            source_format = 'CSV'
        elif suffix == '.xlsx':
            sheet_name, header_row, headers, records = read_xlsx_records(
                content,
                preferred_sheet_names=('product_sth', 'products', 'product'),
                aliases=PRODUCT_ALIASES,
                required_fields=PRODUCT_REQUIRED_FIELDS,
            )
            source_format = 'XLSX'
        else:
            raise SourceImportError('Product source must use the .csv or .xlsx extension.')

        rows_received = len(records) + len(rejected_rows)
        parsed, errors, duplicate_codes, skipped_empty = _parse_product_records(records)
        if source_format == 'XLSX' and errors:
            raise SourceImportError('; '.join(errors[:25]))

        if source_format == 'CSV':
            duplicate_set = set(duplicate_codes)
            valid_rows = []
            for row in parsed:
                row_errors = list(row['validation_errors'])
                if row['product_code_normalized'] in duplicate_set:
                    row_errors.append(
                        f'Row {row["source_row_number"]}: duplicate product code '
                        f'{row["product_code_normalized"]}.'
                    )
                if row_errors:
                    rejected_rows.append({
                        'source_row_number': row['source_row_number'],
                        'column_count': PRODUCT_CSV_COLUMN_COUNT,
                        'raw_values': list((row.get('raw_data') or {}).values()),
                        'validation_errors': row_errors,
                    })
                else:
                    valid_rows.append(row)
            parsed = valid_rows

        if not parsed:
            raise SourceImportError('No valid product rows were found in the source file.')

        comparison = _comparison_summary(parsed, client=external_file.client)
        source_skus = comparison['source_skus']
        django_skus = comparison['django_skus']
        duplicate_file = (
            ExternalDataFile.objects.filter(
                client=external_file.client,
                file_type='PRODUCTS',
                sha256=calculated_hash,
            )
            .exclude(pk=external_file.pk)
            .order_by('-uploaded_at')
            .first()
        )

        warnings = []
        if duplicate_file:
            warnings.append(f'Duplicate content already exists in file #{duplicate_file.pk}.')
        if rejected_rows:
            warnings.append(
                f'{len(rejected_rows)} row(s) were isolated and did not enter valid staging.'
            )

        dimension_counts = Counter(_dimension_status(row) for row in parsed)

        summary = {
            'source_type': 'PRODUCTS',
            'source_filename_expected': 'products.csv',
            'source_format': source_format,
            'encoding': encoding,
            'worksheet': sheet_name,
            'header_row': header_row,
            'headers': headers,
            'rows_received': rows_received,
            'rows_valid': len(parsed),
            'rows_invalid': len(rejected_rows),
            'rows_skipped_empty': skipped_empty,
            'duplicate_skus': duplicate_codes,
            'dimensions_complete': dimension_counts['COMPLETE'],
            'dimensions_zero_or_missing': dimension_counts['ZERO_OR_MISSING'],
            'dimensions_partial': dimension_counts['PARTIAL'],
            'django_products_matched': comparison['matched'],
            'django_products_unchanged': comparison['unchanged'],
            'django_products_different': comparison['different'],
            'difference_counts': comparison['difference_counts'],
            'source_products_not_in_django': len(source_skus - django_skus),
            'django_products_missing_from_source': len(django_skus - source_skus),
            'source_products_not_in_django_preview': comparison['source_only'][:25],
            'django_products_missing_from_source_preview': comparison['django_only'][:25],
            'duplicate_file_id': duplicate_file.pk if duplicate_file else None,
            'duplicate_file_status': duplicate_file.status if duplicate_file else None,
            'reference_only': True,
            'operational_tables_updated': False,
            'warnings': warnings,
            'errors': [],
            'rejected_preview': rejected_rows[:25],
            'preview': [
                {
                    'row': row['source_row_number'],
                    'sku': row['product_code_normalized'],
                    'name': row['name'],
                    'length_mm': str(row['length_mm']) if row['length_mm'] is not None else '',
                    'width_mm': str(row['width_mm']) if row['width_mm'] is not None else '',
                    'height_mm': str(row['height_mm']) if row['height_mm'] is not None else '',
                    'weight_kg': str(row['weight_kg']) if row['weight_kg'] is not None else '',
                    'cubic_m3': str(row['cubic_m3']) if row['cubic_m3'] is not None else '',
                    'pallet': str(row['pallet']) if row['pallet'] is not None else '',
                    'status': row['source_status'],
                }
                for row in parsed[:25]
            ],
        }

        now = timezone.now()
        with transaction.atomic():
            locked_file = ExternalDataFile.objects.select_for_update().get(pk=external_file.pk)
            ProductSourceRow.objects.filter(external_file=locked_file).delete()
            ProductSourceRejectedRow.objects.filter(external_file=locked_file).delete()
            ProductSourceRow.objects.bulk_create(
                [ProductSourceRow(external_file=locked_file, **row) for row in parsed],
                batch_size=500,
            )
            ProductSourceRejectedRow.objects.bulk_create(
                [ProductSourceRejectedRow(external_file=locked_file, **row) for row in rejected_rows],
                batch_size=500,
            )
            locked_file.sha256 = calculated_hash
            locked_file.file_size_bytes = len(content)
            locked_file.validation_summary = summary
            locked_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
            locked_file.validated_at = now
            locked_file.status = 'VALIDATED'
            locked_file.error_message = ''
            locked_file.save(
                update_fields=[
                    'sha256', 'file_size_bytes', 'validation_summary', 'validated_by',
                    'validated_at', 'status', 'error_message',
                ]
            )

        create_audit_event(
            event_type='PRODUCT_SOURCE_VALIDATED',
            message=f'Product reference source validated for {external_file.client.code}.',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            metadata={
                'sha256': calculated_hash,
                **{key: value for key, value in summary.items() if key not in {'preview', 'headers'}},
            },
            request=request,
            request_id=request_id,
        )
        return summary
    except Exception as exc:
        error = exc if isinstance(exc, SourceImportError) else SourceImportError(str(exc))
        ProductSourceRow.objects.filter(external_file=external_file).delete()
        ProductSourceRejectedRow.objects.filter(external_file=external_file).delete()
        external_file.status = 'VALIDATION_FAILED'
        external_file.error_message = str(error)
        external_file.validation_summary = {
            'source_type': 'PRODUCTS',
            'rows_received': 0,
            'rows_valid': 0,
            'rows_invalid': 1,
            'reference_only': True,
            'operational_tables_updated': False,
            'warnings': [],
            'errors': [str(error)],
            'preview': [],
        }
        external_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
        external_file.validated_at = timezone.now()
        external_file.save(
            update_fields=[
                'status', 'error_message', 'validation_summary', 'validated_by', 'validated_at',
            ]
        )
        create_audit_event(
            event_type='PRODUCT_SOURCE_VALIDATION_FAILED',
            message=f'Product reference validation failed for {external_file.client.code}: {error}',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            severity='ERROR',
            metadata={
                'error_type': error.__class__.__name__,
                'error_message': str(error),
                'operational_tables_updated': False,
            },
            request=request,
            request_id=request_id,
        )
        raise error

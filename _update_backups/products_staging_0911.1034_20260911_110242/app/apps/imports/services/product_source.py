from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.imports.models import ExternalDataFile, ProductSourceRow
from apps.imports.services.audit import create_audit_event
from apps.imports.services.xlsx_reader import (
    SourceImportError,
    calculate_sha256,
    normalize_sku,
    parse_decimal,
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


def validate_product_source_file(external_file: ExternalDataFile, *, actor=None, request=None) -> dict:
    if external_file.file_type != 'PRODUCTS':
        raise SourceImportError('Only PRODUCTS files can be validated by this operation.')

    request_id = hashlib.sha256(
        f'product-source:{timezone.now().isoformat()}:{external_file.pk}'.encode()
    ).hexdigest()[:32]

    try:
        content = read_file_bytes(external_file)
        calculated_hash = calculate_sha256(content)
        sheet_name, header_row, headers, records = read_xlsx_records(
            content,
            preferred_sheet_names=('product_sth', 'products', 'product'),
            aliases=PRODUCT_ALIASES,
            required_fields=PRODUCT_REQUIRED_FIELDS,
        )
        parsed, errors, duplicate_codes, skipped_empty = _parse_product_records(records)
        if errors:
            raise SourceImportError('; '.join(errors[:25]))
        if not parsed:
            raise SourceImportError('No valid product rows were found in the workbook.')

        source_skus = {row['product_code_normalized'] for row in parsed}
        django_skus = {
            normalize_sku(value)
            for value in Product.objects.filter(client=external_file.client).values_list('sku', flat=True)
        }
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

        summary = {
            'source_type': 'PRODUCTS',
            'source_filename_expected': 'product_sth.xlsx',
            'worksheet': sheet_name,
            'header_row': header_row,
            'headers': headers,
            'rows_received': len(records),
            'rows_valid': len(parsed),
            'rows_invalid': 0,
            'rows_skipped_empty': skipped_empty,
            'duplicate_skus': duplicate_codes,
            'django_products_matched': len(source_skus & django_skus),
            'source_products_not_in_django': len(source_skus - django_skus),
            'django_products_missing_from_source': len(django_skus - source_skus),
            'source_products_not_in_django_preview': sorted(source_skus - django_skus)[:25],
            'duplicate_file_id': duplicate_file.pk if duplicate_file else None,
            'duplicate_file_status': duplicate_file.status if duplicate_file else None,
            'reference_only': True,
            'operational_tables_updated': False,
            'warnings': warnings,
            'errors': [],
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
            ProductSourceRow.objects.bulk_create(
                [ProductSourceRow(external_file=locked_file, **row) for row in parsed],
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

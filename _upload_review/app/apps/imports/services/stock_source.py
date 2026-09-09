from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.imports.models import ExternalDataFile, StockSourceRow
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


STOCK_ALIASES = {
    'movement_number': ('stock_mov_no', 'movement number', 'movement_number', 'mov no'),
    'stock_date': ('stock_date', 'stock date', 'date'),
    'customer': ('stock_customer', 'customer', 'client'),
    'product_code': ('stock_product', 'product', 'product code', 'product_code', 'sku'),
    'sql_name': ('stock_sql_name', 'sql name', 'product name', 'name'),
    'quantity': ('stock_quantity', 'quantity', 'qty'),
    'pallet': ('stock_pallet', 'pallet', 'pallets'),
    'group1': ('stock_group1', 'group1', 'group 1'),
    'location': ('stock_location', 'location'),
    'stock_class': ('stock_class', 'class'),
    'sql_stock_ref': ('stock_sql_stock_ref', 'sql stock ref', 'stock ref'),
    'weight': ('stock_weight', 'weight', 'weight kg', 'weight_kg'),
    'cubic': ('stock_cubic', 'cubic', 'cubic m3', 'cubic_m3'),
    'depot': ('stock_depot', 'depot'),
    'sql_group': ('stock_sql_group', 'sql group'),
    'sql_group1': ('stock_sql_group1', 'sql group1', 'sql group 1'),
    'expiry': ('stock_expiry', 'expiry', 'expiry date'),
    'pallet_ref': ('stock_pallet_ref', 'pallet ref', 'pallet reference'),
    'serial_no': ('stock_serial_no', 'serial no', 'serial number'),
    'status': ('stock_status', 'status'),
}
STOCK_REQUIRED_FIELDS = tuple(STOCK_ALIASES)


def _is_empty_placeholder(record: dict[str, Any]) -> bool:
    if normalize_sku(record.get('product_code')):
        return False
    meaningful_text = any(
        value_to_text(record.get(field)).strip()
        for field in (
            'movement_number', 'stock_date', 'customer', 'sql_name', 'group1', 'location',
            'stock_class', 'sql_stock_ref', 'depot', 'sql_group', 'sql_group1', 'expiry',
            'pallet_ref', 'serial_no', 'status',
        )
    )
    numeric_values = []
    for field in ('quantity', 'pallet', 'weight', 'cubic'):
        value = record.get(field)
        if value in (None, ''):
            continue
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            return False
    return not meaningful_text and all(value == 0 for value in numeric_values)


def _parse_stock_records(records: list[dict[str, Any]]):
    parsed: list[dict[str, Any]] = []
    errors: list[str] = []
    skipped_empty = 0

    for record in records:
        row_number = int(record['_row_number'])
        if _is_empty_placeholder(record):
            skipped_empty += 1
            continue

        row_errors: list[str] = []
        code_raw = value_to_text(record.get('product_code'))
        code_normalized = normalize_sku(record.get('product_code'))
        if not code_normalized:
            row_errors.append(f'Row {row_number}: stock product code is required.')

        parsed_row = {
            'source_row_number': row_number,
            'movement_number': value_to_text(record.get('movement_number')),
            'stock_date_raw': value_to_text(record.get('stock_date')),
            'customer': value_to_text(record.get('customer')),
            'product_code_raw': code_raw,
            'product_code_normalized': code_normalized,
            'sql_name': value_to_text(record.get('sql_name')),
            'quantity': parse_decimal(
                record.get('quantity'), field_label='stock quantity', row_number=row_number,
                errors=row_errors,
            ),
            'pallet': parse_decimal(
                record.get('pallet'), field_label='stock pallet', row_number=row_number,
                errors=row_errors,
            ),
            'group1': value_to_text(record.get('group1')),
            'location': value_to_text(record.get('location')),
            'stock_class': value_to_text(record.get('stock_class')),
            'sql_stock_ref': value_to_text(record.get('sql_stock_ref')),
            'weight_kg': parse_decimal(
                record.get('weight'), field_label='stock weight', row_number=row_number,
                errors=row_errors,
            ),
            'cubic_m3': parse_decimal(
                record.get('cubic'), field_label='stock cubic', row_number=row_number,
                errors=row_errors,
            ),
            'depot': value_to_text(record.get('depot')),
            'sql_group': value_to_text(record.get('sql_group')),
            'sql_group1': value_to_text(record.get('sql_group1')),
            'expiry_raw': value_to_text(record.get('expiry')),
            'pallet_ref': value_to_text(record.get('pallet_ref')),
            'serial_no': value_to_text(record.get('serial_no')),
            'source_status': value_to_text(record.get('status')),
            'raw_data': record.get('_raw_data') or {},
            'validation_errors': row_errors,
        }
        parsed.append(parsed_row)
        errors.extend(row_errors)

    counts = Counter(row['product_code_normalized'] for row in parsed if row['product_code_normalized'])
    duplicate_codes = sorted(code for code, count in counts.items() if count > 1)
    return parsed, errors, duplicate_codes, skipped_empty


def validate_stock_source_file(external_file: ExternalDataFile, *, actor=None, request=None) -> dict:
    if external_file.file_type != 'STOCK':
        raise SourceImportError('Only STOCK files can be validated by this operation.')

    request_id = hashlib.sha256(
        f'stock-source:{timezone.now().isoformat()}:{external_file.pk}'.encode()
    ).hexdigest()[:32]

    try:
        content = read_file_bytes(external_file)
        calculated_hash = calculate_sha256(content)
        sheet_name, header_row, headers, records = read_xlsx_records(
            content,
            preferred_sheet_names=('stock_sth', 'stock', 'stock source'),
            aliases=STOCK_ALIASES,
            required_fields=STOCK_REQUIRED_FIELDS,
        )
        parsed, errors, duplicate_codes, skipped_empty = _parse_stock_records(records)
        if errors:
            raise SourceImportError('; '.join(errors[:25]))
        if not parsed:
            raise SourceImportError('No valid stock rows were found in the workbook.')

        source_skus = {row['product_code_normalized'] for row in parsed}
        django_skus = {
            normalize_sku(value)
            for value in Product.objects.filter(client=external_file.client).values_list('sku', flat=True)
        }
        duplicate_file = (
            ExternalDataFile.objects.filter(
                client=external_file.client,
                file_type='STOCK',
                sha256=calculated_hash,
            )
            .exclude(pk=external_file.pk)
            .order_by('-uploaded_at')
            .first()
        )

        warnings = []
        if duplicate_codes:
            warnings.append(
                f'{len(duplicate_codes)} product code(s) occur more than once in the stock source. '
                'All source rows were preserved.'
            )
        if duplicate_file:
            warnings.append(f'Duplicate content already exists in file #{duplicate_file.pk}.')

        summary = {
            'source_type': 'STOCK',
            'source_filename_expected': 'stock_sth.xlsx',
            'worksheet': sheet_name,
            'header_row': header_row,
            'headers': headers,
            'rows_received': len(records),
            'rows_valid': len(parsed),
            'rows_invalid': 0,
            'rows_skipped_empty': skipped_empty,
            'duplicate_skus': duplicate_codes,
            'django_products_matched': len(source_skus & django_skus),
            'stock_products_not_in_django': len(source_skus - django_skus),
            'stock_products_not_in_django_preview': sorted(source_skus - django_skus)[:25],
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
                    'name': row['sql_name'],
                    'quantity': str(row['quantity']) if row['quantity'] is not None else '',
                    'pallet': str(row['pallet']) if row['pallet'] is not None else '',
                    'weight_kg': str(row['weight_kg']) if row['weight_kg'] is not None else '',
                    'cubic_m3': str(row['cubic_m3']) if row['cubic_m3'] is not None else '',
                    'location': row['location'],
                    'status': row['source_status'],
                }
                for row in parsed[:25]
            ],
        }

        now = timezone.now()
        with transaction.atomic():
            locked_file = ExternalDataFile.objects.select_for_update().get(pk=external_file.pk)
            StockSourceRow.objects.filter(external_file=locked_file).delete()
            StockSourceRow.objects.bulk_create(
                [StockSourceRow(external_file=locked_file, **row) for row in parsed],
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
            event_type='STOCK_SOURCE_VALIDATED',
            message=f'Stock reference source validated for {external_file.client.code}.',
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
        StockSourceRow.objects.filter(external_file=external_file).delete()
        external_file.status = 'VALIDATION_FAILED'
        external_file.error_message = str(error)
        external_file.validation_summary = {
            'source_type': 'STOCK',
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
            event_type='STOCK_SOURCE_VALIDATION_FAILED',
            message=f'Stock reference validation failed for {external_file.client.code}: {error}',
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

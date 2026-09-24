from __future__ import annotations

import hashlib
import csv
import io
from collections import Counter
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone
from apps.clients.models import Client
from apps.authentication_gateway.services import allowed_clients_for, CalculatorAccessDenied

from apps.imports.models import (
    ExternalDataFile,
    ProductSourceRejectedRow,
    ProductSourceRow,
)
from apps.imports.services.audit import create_audit_event
from apps.imports.services.product_repair import build_product_repair_proposal
from apps.imports.services.product_file_adapters import read_product_file
from apps.imports.services.xlsx_reader import (
    SourceImportError,
    calculate_sha256,
    normalize_product_sku,
    parse_decimal,
    read_file_bytes,
    value_to_text,
)
from apps.products.models import Product
from apps.products.identity import normalize_customer, product_identity, valid_customer


PRODUCT_ALIASES = {
    'customer': ('customer', 'customer code', 'customer_code'),
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
PRODUCT_REQUIRED_FIELDS = tuple(field for field in PRODUCT_ALIASES if field != 'customer')
PRODUCT_CSV_COLUMN_COUNT = 13


def _is_empty_placeholder(record: dict[str, Any]) -> bool:
    if normalize_product_sku(record.get('code')):
        return False
    meaningful_text = any(
        value_to_text(record.get(field)).strip()
        for field in ('customer', 'name', 'description', 'category', 'comment', 'status')
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


def _parse_product_records(records: list[dict[str, Any]], *, with_customer=False):
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
        code_normalized = normalize_product_sku(record.get('code'))
        customer_code = normalize_customer(record.get('customer')) if with_customer else ''
        if with_customer and not valid_customer(customer_code):
            row_errors.append(f'Row {row_number}: CUSTOMER is missing or invalid.')
        if not code_normalized:
            row_errors.append(f'Row {row_number}: product code is required.')

        parsed_row = {
            'source_row_number': row_number,
            'product_code_raw': code_raw,
            'product_code_normalized': code_normalized,
            'customer_code': customer_code,
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

    counts = Counter(
        (row['customer_code'], row['product_code_normalized']) for row in parsed
        if row['product_code_normalized'] and (not with_customer or valid_customer(row['customer_code']))
    )
    duplicate_codes = sorted(product_identity(customer, sku) for (customer, sku), count in counts.items() if count > 1)
    for identity in duplicate_codes:
        duplicate_rows = [str(row['source_row_number']) for row in parsed
                          if product_identity(row['customer_code'], row['product_code_normalized']) == identity]
        errors.append(f'Duplicate CUSTOMER / product code {identity} on rows {", ".join(duplicate_rows)}.')

    return parsed, errors, duplicate_codes, skipped_empty


def _dimension_status(row: dict[str, Any]) -> str:
    values = [row.get('length_mm'), row.get('width_mm'), row.get('height_mm')]
    positive = [value is not None and value > 0 for value in values]
    if all(positive):
        return 'COMPLETE'
    if not any(positive):
        return 'ZERO_OR_MISSING'
    return 'PARTIAL'


def _product_map(client) -> dict[tuple[str, str], Product]:
    return {
        ('', normalize_product_sku(product.sku)): product
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
    source_skus = {('', row['product_code_normalized']) for row in parsed}
    django_skus = set(products)
    unchanged = 0
    different = 0
    difference_counts = Counter()
    for row in parsed:
        status, differences = _comparison_details(
            row,
            products.get(('', row['product_code_normalized'])),
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
        'source_only': [product_identity(*key) for key in sorted(source_skus - django_skus)],
        'django_only': [product_identity(*key) for key in sorted(django_skus - source_skus)],
    }


def build_product_source_validation_report(external_file: ExternalDataFile) -> str:
    """Return an Excel-friendly detail CSV without changing operational data."""
    products = _product_map(external_file.client)
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    include_customer = bool((external_file.validation_summary or {}).get('source_customer_column'))
    def write_row(values):
        writer.writerow(values if include_customer else values[:3] + values[4:])

    write_row([
        'record_status', 'source_row', 'source_columns', 'customer', 'sku', 'comparison',
        'different_fields', 'validation_errors', 'name', 'dimension_status',
        'source_length_mm', 'source_width_mm', 'source_height_mm',
        'source_weight_kg', 'source_cubic_m3', 'source_pallet', 'source_status',
        'current_length_m', 'current_width_m', 'current_height_m',
        'current_weight_kg', 'current_cubic_m3',
    ])
    source_column_count = int(
        (external_file.validation_summary or {}).get('source_column_count')
        or PRODUCT_CSV_COLUMN_COUNT
    )
    for row in ProductSourceRow.objects.filter(external_file=external_file).iterator():
        product = products.get(('', row.product_code_normalized))
        comparison, differences = _comparison_details(
            row,
            product,
        )
        write_row([
            'VALID', row.source_row_number, source_column_count, external_file.client.code if include_customer else '',
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
    for row in ProductSourceRejectedRow.objects.filter(
        external_file=external_file
    ).exclude(repair_status='APPROVED').iterator():
        raw = list(row.raw_values or [])
        write_row([
            'REJECTED', row.source_row_number, row.column_count or '', external_file.client.code if include_customer else '',
            raw[1] if include_customer and len(raw) > 1 else raw[0] if raw else '', '', '', '|'.join(row.validation_errors or []),
            raw[2] if include_customer and len(raw) > 2 else raw[1] if len(raw) > 1 else '', '', '', '', '', '', '', '', '',
            '', '', '', '', '',
        ])
    return '\ufeff' + stream.getvalue()


def validate_product_source_file(external_file: ExternalDataFile, *, actor=None, request=None) -> dict:
    if external_file.file_type != 'PRODUCTS':
        raise SourceImportError('Only PRODUCTS files can be validated by this operation.')
    if ExternalDataFile.objects.filter(
        file_type='PRODUCTS', validation_summary__partition_source_id=external_file.pk,
    ).exists():
        raise SourceImportError('This source has client partitions. Upload a new snapshot instead of re-validating it.')
    if any(batch.get('batch_id') and not batch.get('rolled_back_at') for batch in
           (external_file.import_summary or {}).get('product_reconciliation_apply_batches', [])
           if isinstance(batch, dict)):
        raise SourceImportError('An applied Product source is immutable. Upload a new file instead.')
    if ProductSourceRejectedRow.objects.filter(
        external_file=external_file,
        repair_status__in={'PROPOSED', 'APPROVED'},
    ).exists():
        raise SourceImportError(
            'This Product source already has saved repair reviews. Upload a new source '
            'snapshot instead of re-validating this reviewed file.'
        )

    request_id = hashlib.sha256(
        f'product-source:{timezone.now().isoformat()}:{external_file.pk}'.encode()
    ).hexdigest()[:32]

    try:
        content = read_file_bytes(external_file)
        calculated_hash = calculate_sha256(content)
        source = read_product_file(
            content,
            external_file.original_filename,
            aliases=PRODUCT_ALIASES,
            required_fields=PRODUCT_REQUIRED_FIELDS,
            expected_csv_column_count=PRODUCT_CSV_COLUMN_COUNT,
        )
        sheet_name = source.worksheet
        header_row = source.header_row
        headers = source.headers
        records = source.records
        rejected_rows = list(source.rejected_rows)
        encoding = source.encoding
        source_format = source.source_format
        with_customer = any(str(header).strip().lower() in {'customer', 'customer code', 'customer_code'} for header in headers)
        if source_format == 'CSV' and source.source_column_count != (14 if with_customer else 13):
            raise SourceImportError(f'A Product CSV with this header must contain {14 if with_customer else 13} columns.')

        rows_received = len(records) + len(rejected_rows)
        parsed, errors, duplicate_codes, skipped_empty = _parse_product_records(records, with_customer=with_customer)
        if source_format in {'XLS', 'XLSX'} and errors:
            raise SourceImportError('; '.join(errors[:25]))

        if source_format == 'CSV':
            duplicate_set = set(duplicate_codes)
            valid_rows = []
            for row in parsed:
                row_errors = list(row['validation_errors'])
                if product_identity(row['customer_code'], row['product_code_normalized']) in duplicate_set:
                    row_errors.append(
                        f'Row {row["source_row_number"]}: duplicate product code '
                        f'{row["product_code_normalized"]}.'
                    )
                if row_errors:
                    rejected_rows.append({
                        'source_row_number': row['source_row_number'],
                        'column_count': source.source_column_count,
                        'raw_values': list((row.get('raw_data') or {}).values()),
                        'validation_errors': row_errors,
                    })
                else:
                    valid_rows.append(row)
            parsed = valid_rows

        if not parsed:
            raise SourceImportError('No valid product rows were found in the source file.')

        # The file's CUSTOMER is a Client code. Each reconciliation source is
        # owned by exactly one Client, preserving the existing decision and
        # memory boundaries even when the uploaded workbook contains many.
        partition_customer = (external_file.validation_summary or {}).get('partition_customer')
        other_clients = []
        if with_customer:
            codes = {row['customer_code'] for row in parsed}
            codes.update(normalize_customer((row.get('raw_values') or [''])[0])
                         for row in rejected_rows if row.get('raw_values'))
            existing = {client.code for client in Client.objects.filter(code__in=codes, active=True)}
            unknown = codes - existing
            if unknown:
                raise SourceImportError('Unknown or inactive Client code(s) in CUSTOMER: ' + ', '.join(sorted(unknown)))
            if actor is not None and getattr(actor, 'is_authenticated', False) and not actor.is_superuser:
                try:
                    authorised = set(allowed_clients_for(actor).values_list('code', flat=True))
                except CalculatorAccessDenied as exc:
                    raise SourceImportError('The user cannot validate Product sources.') from exc
                if not codes.issubset(authorised):
                    raise SourceImportError('CUSTOMER contains a Client the user is not authorised to access.')
            selected = partition_customer or external_file.client.code
            if selected not in codes:
                raise SourceImportError(f'No Product rows belong to the selected Client {selected}.')
            if selected != external_file.client.code:
                raise SourceImportError('The partition Client does not match the source Client.')
            other_clients = sorted(codes - {selected}) if not partition_customer else []
            parsed = [row for row in parsed if row['customer_code'] == selected]
            rejected_rows = [row for row in rejected_rows
                             if normalize_customer((row.get('raw_values') or [''])[0]) == selected]
            if not parsed:
                raise SourceImportError(f'No valid Product rows belong to Client {selected}.')
            rows_received = len(parsed) + len(rejected_rows)
            # CUSTOMER stays in raw_data and validation provenance, never in Product.
            for row in parsed:
                row['customer_code'] = ''
        elif partition_customer:
            raise SourceImportError('The partitioned workbook no longer contains CUSTOMER.')

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

        warnings = list(source.warnings)
        if duplicate_file:
            warnings.append(f'Duplicate content already exists in file #{duplicate_file.pk}.')
        if rejected_rows:
            warnings.append(
                f'{len(rejected_rows)} row(s) were isolated and did not enter valid staging.'
            )

        dimension_counts = Counter(_dimension_status(row) for row in parsed)

        summary = {
            'source_type': 'PRODUCTS',
            'source_filename_expected': 'products.xls',
            'source_format': source_format,
            'encoding': encoding,
            'worksheet': sheet_name,
            'header_row': header_row,
            'headers': headers,
            'customer_column': False,
            'source_customer_column': with_customer,
            'resolved_client_code': external_file.client.code,
            'partition_customer': partition_customer or '',
            'partition_source_id': (external_file.validation_summary or {}).get('partition_source_id'),
            'partition_client_codes': other_clients,
            'source_column_count': source.source_column_count,
            'rows_received': rows_received,
            'rows_valid': len(parsed),
            'rows_invalid': len(rejected_rows),
            'rows_pending_repair': len(rejected_rows),
            'rows_repaired_approved': 0,
            'rows_valid_effective': len(parsed),
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
                [
                    ProductSourceRejectedRow(
                        external_file=locked_file,
                        proposed_data=build_product_repair_proposal(
                            (row.get('raw_values') or [])[1:] if with_customer
                            else row.get('raw_values') or []
                        ),
                        customer_code='',
                        **row,
                    )
                    for row in rejected_rows
                ],
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
            for code in other_clients:
                child = ExternalDataFile.objects.create(
                    client=Client.objects.get(code=code), file_type='PRODUCTS',
                    source_method='COMMAND', original_filename=external_file.original_filename,
                    uploaded_file=external_file.uploaded_file.name if external_file.uploaded_file else None,
                    stored_path=external_file.stored_path, uploaded_by=actor if getattr(actor, 'is_authenticated', False) else None,
                    validation_summary={'partition_customer': code, 'partition_source_id': external_file.pk},
                )
                validate_product_source_file(child, actor=actor, request=request)

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

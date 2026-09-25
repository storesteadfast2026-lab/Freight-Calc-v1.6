"""Read-only validation of company-wide Translogic Product Master workbooks."""

from collections import Counter
from hashlib import sha256

from django.db import transaction
from django.utils import timezone

from apps.clients.models import Customer
from apps.imports.models import ProductMaster
from apps.imports.services.product_file_adapters import read_product_file
from apps.imports.services.product_source import (
    PRODUCT_ALIASES, PRODUCT_CSV_COLUMN_COUNT, PRODUCT_REQUIRED_FIELDS,
)
from apps.imports.services.xlsx_reader import SourceImportError, normalize_product_sku
from apps.products.identity import normalize_customer, valid_customer


PREVIEW_LIMIT = 100


def validate_product_master(master_id, *, actor=None):
    """Resolve CUSTOMER for every row; never touch Product or Client records."""
    master = ProductMaster.objects.get(pk=master_id)
    if master.status == 'VALIDATED':
        raise SourceImportError('This Product Master is already validated. Upload a new snapshot.')
    try:
        master.original_file.open('rb')
        try:
            content = master.original_file.read()
        finally:
            master.original_file.close()
        if sha256(content).hexdigest() != master.sha256:
            raise SourceImportError('The stored Product Master does not match its upload checksum.')
        source = read_product_file(
            content, master.original_filename, aliases=PRODUCT_ALIASES,
            required_fields=PRODUCT_REQUIRED_FIELDS,
            expected_csv_column_count=PRODUCT_CSV_COLUMN_COUNT,
        )
        if not any(str(header).strip().lower() in {'customer', 'customer code', 'customer_code'}
                   for header in source.headers):
            raise SourceImportError('Product Master requires a CUSTOMER column.')
        records = source.records
        codes = {normalize_customer(row.get('customer')) for row in records}
        customers = {
            customer.code: customer
            for customer in Customer.objects.filter(code__in=(codes - {''})).select_related('linked_client')
        }
        counts = Counter()
        per_customer = Counter()
        identities = Counter()
        preview = []
        for row in records:
            code = normalize_customer(row.get('customer'))
            sku = normalize_product_sku(row.get('code'))
            customer = customers.get(code)
            if not code:
                status = 'EMPTY_CUSTOMER'
            elif not valid_customer(code) or customer is None:
                status = 'UNKNOWN_CUSTOMER'
            elif customer.linked_client_id:
                status = 'LINKED'
            else:
                status = 'UNLINKED'
            counts[status] += 1
            per_customer[code or '(empty)'] += 1
            if sku:
                identities[(code, sku)] += 1
            if len(preview) < PREVIEW_LIMIT:
                preview.append({
                    'row': row['_row_number'], 'customer_code': code, 'sku': sku,
                    'customer_name': customer.name if customer else '',
                    'calculator_customer': (
                        customer.linked_client.code if customer and customer.linked_client_id else ''
                    ),
                    'status': status,
                })
        if not records and not source.rejected_rows:
            raise SourceImportError('No Product rows were found in the workbook.')
        summary = {
            'rows_read': len(records), 'rows_rejected_by_reader': len(source.rejected_rows),
            'status_counts': dict(counts), 'customer_counts': dict(sorted(per_customer.items())),
            'duplicate_customer_sku_pairs': sum(value - 1 for value in identities.values() if value > 1),
            'preview': preview, 'preview_limit': PREVIEW_LIMIT,
            'source_format': source.source_format, 'worksheet': source.worksheet,
            'header_row': source.header_row, 'warnings': list(source.warnings),
            'operational_tables_updated': False,
        }
        new_status, error = 'VALIDATED', ''
    except (SourceImportError, OSError, ValueError) as exc:
        summary, new_status, error = {}, 'VALIDATION_FAILED', str(exc)
    with transaction.atomic():
        locked = ProductMaster.objects.select_for_update().get(pk=master_id)
        if locked.status == 'VALIDATED':
            raise SourceImportError('This Product Master is already validated. Upload a new snapshot.')
        locked.status = new_status
        locked.validation_summary = summary
        locked.error_message = error
        locked.validated_at = timezone.now()
        locked.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
        locked.save(update_fields=[
            'status', 'validation_summary', 'error_message', 'validated_at', 'validated_by',
        ])
    return locked

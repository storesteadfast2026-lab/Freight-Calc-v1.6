"""Read-only validation of company-wide Translogic Product Master workbooks."""

from collections import Counter
from hashlib import sha256
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.clients.models import Customer
from apps.imports.models import ExternalDataFile, ProductMaster, ProductSourceRow
from apps.imports.services.product_file_adapters import read_product_file
from apps.imports.services.product_source import (
    PRODUCT_ALIASES, PRODUCT_CSV_COLUMN_COUNT, PRODUCT_REQUIRED_FIELDS,
    _parse_product_records,
)
from apps.imports.services.xlsx_reader import SourceImportError, normalize_product_sku
from apps.imports.services.product_reconciliation_apply import (
    apply_product_reconciliation, build_product_apply_plan,
    new_product_values,
)
from apps.imports.services.product_reconciliation_workspace import (
    derive_freight_type_from_pallet, save_product_reconciliation_decisions,
)
from apps.products.models import Product
from apps.products.identity import normalize_customer, valid_customer


PREVIEW_LIMIT = 100


def new_product_warnings(row, client):
    """Validate Source-only values against the existing operational Product model."""
    if row['status'] != 'SOURCE_ONLY':
        return ['Product already exists or Source SKU is duplicated.']
    source = row['source_values']
    warnings = list(row['source'].validation_errors or [])
    freight, freight_warning = derive_freight_type_from_pallet(source.get('pallet'))
    if freight_warning:
        warnings.append(freight_warning)
    fields = ('length_m', 'width_m', 'height_m', 'weight_kg', 'cubic_m3')
    for field in fields:
        value = source.get(field)
        if value is None or not Decimal(value).is_finite() or Decimal(value) < 0:
            warnings.append(f'{field} must be a non-negative number.')
    if any(source.get(key) is None or source[key] <= 0
           for key in ('length_m', 'width_m', 'height_m')):
        warnings.append('New Products require positive dimensions.')
    if not warnings:
        try:
            Product(client=client, sku=row['sku'],
                    **new_product_values({**source, 'freight_type': freight}),
                    active=True, source_row=row['source_row_number']).full_clean(
                        validate_unique=False)
        except ValidationError as exc:
            warnings.append(str(exc))
    return warnings


@transaction.atomic
def import_new_products_from_master(master, customer, selected_rows, *, actor=None, request=None):
    """Bridge an approved selection into the existing draft, Apply and audit workflow."""
    master = ProductMaster.objects.select_for_update().get(pk=master.pk, status='VALIDATED')
    expected_client_id = customer.linked_client_id
    customer = Customer.objects.select_for_update().select_related('linked_client').get(pk=customer.pk)
    if not expected_client_id or customer.linked_client_id != expected_client_id:
        raise SourceImportError('Customer linkage changed. Review the selection again.')
    refreshed, invalid = reconciliation_rows_for_customer(master, customer, include_invalid=True)
    if invalid:
        # Invalid rows stay outside staging; their SKU must not be imported via another row.
        invalid_skus = {row['product_code_normalized'] for row in invalid}
    else:
        invalid_skus = set()
    requested = set(selected_rows)
    if not requested or len(requested) != len(selected_rows):
        raise SourceImportError('Select distinct, eligible Source-only SKUs.')
    from apps.imports.services.product_reconciliation_workspace import build_workspace
    source = ExternalDataFile(client=customer.linked_client, file_type='PRODUCTS',
                              status='VALIDATED', original_filename=master.original_filename)
    rows, _ = build_workspace(source, source_rows=refreshed,
                              pending_rejected=0, include_decisions=False)
    by_sku = {row['sku']: row for row in rows if row['status'] == 'SOURCE_ONLY'
              and row['sku'] not in invalid_skus
              and not new_product_warnings(row, customer.linked_client)}
    if requested - by_sku.keys():
        raise SourceImportError('Selection changed or includes an ineligible Product. Review again.')
    staged = [by_sku[sku]['source'] for sku in selected_rows]
    external_file = ExternalDataFile.objects.create(
        client=customer.linked_client, file_type='PRODUCTS', status='VALIDATED',
        source_method='COMMAND', original_filename=master.original_filename,
        uploaded_by=actor, validated_by=actor, validated_at=timezone.now(),
        sha256=master.sha256,
        import_summary={'product_master_id': master.pk, 'product_master_sha256': master.sha256,
                        'customer_code': customer.code, 'source_row_numbers': [r.source_row_number for r in staged]},
    )
    ProductSourceRow.objects.bulk_create([
        ProductSourceRow(**{field.attname: getattr(source_row, field.attname)
                            for field in ProductSourceRow._meta.concrete_fields
                            if field.attname not in {'id', 'external_file_id', 'created_at'}},
                         external_file=external_file)
        for source_row in staged
    ])
    save_product_reconciliation_decisions(
        external_file, skus=selected_rows,
        field_decisions={key: 'SOURCE' for key in (
            'name', 'description', 'dimensions', 'weight', 'cubic', 'freight_type')},
        notes=f'Product Master #{master.pk} Source-only import; reviewed in Preview.',
        actor=actor, request=request,
    )
    plan = build_product_apply_plan(external_file.pk)
    if not plan['can_apply'] or plan['create_count'] != len(selected_rows):
        raise SourceImportError('Import preview changed; no Products were created. ' +
                                '; '.join(plan['blockers']))
    batch = apply_product_reconciliation(external_file.pk, actor=actor, request=request)
    return external_file, batch


def reconciliation_rows_for_customer(master, customer, *, include_invalid=False):
    """Return unsaved source rows for one currently linked Customer.

    Preserve the existing Calculator Customer access/authorisation rules.
    Product Master rows must only be exposed to Product Reconciliation within
    the authorised Calculator Customer scope; the global Product Master must
    not bypass existing customer data isolation.
    """
    if master.status != 'VALIDATED' or not customer.linked_client_id:
        raise SourceImportError('A validated Product Master and linked Customer are required.')
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
    selected = [record for record in source.records
                if normalize_customer(record.get('customer')) == customer.code]
    if not selected:
        raise SourceImportError('No Product Master rows belong to this Customer.')
    parsed, _errors, _duplicates, _empty = _parse_product_records(selected, with_customer=True)
    # An invalid selected row cannot enter reconciliation; never repair or
    # silently convert it into a different Customer's staging row.
    if any(row['validation_errors'] for row in parsed) and not include_invalid:
        raise SourceImportError('Selected Customer has invalid Product Master rows.')
    if include_invalid:
        return ([ProductSourceRow(**row) for row in parsed if not row['validation_errors']],
                [row for row in parsed if row['validation_errors']])
    return [ProductSourceRow(**row) for row in parsed]


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

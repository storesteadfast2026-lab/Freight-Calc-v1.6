from __future__ import annotations

from collections import Counter
from decimal import Decimal
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
    json_safe_value,
    normalize_product_sku,
    value_to_text,
)
from apps.products.models import Product


PRODUCT_REPAIR_FIELDS = (
    'code',
    'name',
    'description',
    'category',
    'length_mm',
    'width_mm',
    'height_mm',
    'cubic_m3',
    'quantity',
    'weight_kg',
    'pallet',
    'comment',
    'source_status',
)
TAIL_FIELD_COUNT = 10


class ProductRepairError(Exception):
    """Raised when a rejected Product row cannot be reviewed safely."""


def _remove_one_structural_quote(value: str) -> str:
    value = value.strip()
    return value[:-1] if value.endswith('"') else value


def build_product_repair_proposal(raw_values: list[Any]) -> dict[str, str]:
    """Build an editable proposal without claiming that malformed text is exact."""
    values = [value_to_text(value) for value in (raw_values or [])]
    proposal = {field: '' for field in PRODUCT_REPAIR_FIELDS}
    warning = (
        'This proposal was reconstructed from malformed CSV fields. '
        'Verify name, description, quotation marks, comments and every numeric value before approval.'
    )

    if len(values) == 13:
        mapped = values
    elif len(values) > 13 and len(values) >= TAIL_FIELD_COUNT + 3:
        prefix = values[:-TAIL_FIELD_COUNT]
        tail = values[-TAIL_FIELD_COUNT:]
        description = _remove_one_structural_quote(
            ', '.join(value.strip() for value in prefix[2:])
        )
        mapped = [prefix[0], prefix[1], description, *tail]
    elif len(values) == 12:
        prefix = values[:-TAIL_FIELD_COUNT]
        tail = values[-TAIL_FIELD_COUNT:]
        merged = prefix[1] if len(prefix) > 1 else ''
        if '",' in merged:
            name, description = merged.split('",', 1)
            # The quote immediately before the comma belongs to the short
            # product name (for example a size expressed in inches).
            name = f'{name}"'
            description = _remove_one_structural_quote(description)
        else:
            name, description = merged, ''
        mapped = [prefix[0] if prefix else '', name, description, *tail]
    else:
        proposal['_proposal_warning'] = warning
        return proposal

    if len(mapped) == len(PRODUCT_REPAIR_FIELDS):
        proposal.update(dict(zip(PRODUCT_REPAIR_FIELDS, mapped)))
    proposal['_proposal_warning'] = warning
    return proposal


def _json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        field: json_safe_value(payload.get(field))
        for field in PRODUCT_REPAIR_FIELDS
    }


def _refresh_repair_summary(external_file: ExternalDataFile) -> None:
    rejected = ProductSourceRejectedRow.objects.filter(external_file=external_file)
    staging_rows = list(ProductSourceRow.objects.filter(external_file=external_file))
    products = {
        normalize_product_sku(product.sku): product
        for product in Product.objects.filter(client=external_file.client)
    }
    source_skus = {row.product_code_normalized for row in staging_rows}
    django_skus = set(products)
    dimensions = Counter()
    comparison = Counter()
    difference_counts = Counter()

    for row in staging_rows:
        dimension_values = (row.length_mm, row.width_mm, row.height_mm)
        positive = [value is not None and value > 0 for value in dimension_values]
        dimensions[
            'COMPLETE' if all(positive) else 'ZERO_OR_MISSING' if not any(positive) else 'PARTIAL'
        ] += 1

        product = products.get(row.product_code_normalized)
        if product is None:
            continue
        fields = (
            ('length', row.length_mm, product.length_m, Decimal('1000')),
            ('width', row.width_mm, product.width_m, Decimal('1000')),
            ('height', row.height_mm, product.height_m, Decimal('1000')),
            ('weight', row.weight_kg, product.weight_kg, Decimal('1')),
            ('cubic', row.cubic_m3, product.cubic_m3, Decimal('1')),
        )
        differences = []
        for label, source, current, divisor in fields:
            normalised_source = None if source is None else source / divisor
            if normalised_source != current:
                differences.append(label)
        comparison['DIFFERENT' if differences else 'UNCHANGED'] += 1
        difference_counts.update(differences)

    summary = dict(external_file.validation_summary or {})
    summary['rows_repaired_approved'] = rejected.filter(repair_status='APPROVED').count()
    summary['rows_pending_repair'] = rejected.exclude(repair_status='APPROVED').count()
    summary['rows_valid_effective'] = len(staging_rows)
    summary['dimensions_complete'] = dimensions['COMPLETE']
    summary['dimensions_zero_or_missing'] = dimensions['ZERO_OR_MISSING']
    summary['dimensions_partial'] = dimensions['PARTIAL']
    summary['django_products_matched'] = len(source_skus & django_skus)
    summary['django_products_unchanged'] = comparison['UNCHANGED']
    summary['django_products_different'] = comparison['DIFFERENT']
    summary['difference_counts'] = dict(sorted(difference_counts.items()))
    summary['source_products_not_in_django'] = len(source_skus - django_skus)
    summary['django_products_missing_from_source'] = len(django_skus - source_skus)
    summary['source_products_not_in_django_preview'] = sorted(source_skus - django_skus)[:25]
    summary['django_products_missing_from_source_preview'] = sorted(django_skus - source_skus)[:25]
    summary['operational_tables_updated'] = False
    external_file.validation_summary = summary
    external_file.save(update_fields=['validation_summary'])


def save_product_repair_proposal(
    rejected_row_id: int,
    *,
    payload: dict[str, Any],
    review_note: str = '',
    actor=None,
    request=None,
) -> ProductSourceRejectedRow:
    with transaction.atomic():
        row = (
            ProductSourceRejectedRow.objects.select_for_update()
            .select_related('external_file__client')
            .get(pk=rejected_row_id)
        )
        if row.repair_status == 'APPROVED':
            raise ProductRepairError('An approved repair is immutable.')

        row.proposed_data = _json_payload(payload)
        row.review_note = (review_note or '').strip()
        row.repair_status = 'PROPOSED'
        row.reviewed_by = actor if getattr(actor, 'is_authenticated', False) else None
        row.reviewed_at = timezone.now()
        row.save(update_fields=[
            'proposed_data', 'review_note', 'repair_status', 'reviewed_by', 'reviewed_at',
        ])
        _refresh_repair_summary(row.external_file)
        create_audit_event(
            event_type='PRODUCT_SOURCE_REPAIR_PROPOSED',
            message=(
                f'Product source repair proposal saved for row '
                f'{row.source_row_number}.'
            ),
            actor=actor,
            client=row.external_file.client,
            external_file=row.external_file,
            metadata={
                'rejected_row_id': row.pk,
                'source_row_number': row.source_row_number,
                'proposal': row.proposed_data,
                'review_note': row.review_note,
                'operational_tables_updated': False,
            },
            request=request,
        )
        return row


def approve_product_source_repair(
    rejected_row_id: int,
    *,
    payload: dict[str, Any],
    review_note: str,
    actor=None,
    request=None,
) -> ProductSourceRejectedRow:
    note = (review_note or '').strip()
    if not note:
        raise ProductRepairError('A review note is required for approval.')

    with transaction.atomic():
        row = (
            ProductSourceRejectedRow.objects.select_for_update()
            .select_related('external_file__client')
            .get(pk=rejected_row_id)
        )
        if row.repair_status == 'APPROVED' or row.staged_row_id:
            raise ProductRepairError('This rejected row is already approved into staging.')
        if row.external_file.status != 'VALIDATED':
            raise ProductRepairError('Only rows from a validated Product source can be approved.')

        code_raw = value_to_text(payload.get('code')).strip()
        code_normalized = normalize_product_sku(code_raw)
        if not code_normalized:
            raise ProductRepairError('Product code is required.')
        if ProductSourceRow.objects.filter(
            external_file=row.external_file,
            product_code_normalized=code_normalized,
        ).exists():
            raise ProductRepairError(
                f'Product code {code_normalized} already exists in valid staging for this file.'
            )

        saved_payload = _json_payload(payload)
        staged = ProductSourceRow.objects.create(
            external_file=row.external_file,
            source_row_number=row.source_row_number,
            product_code_raw=code_raw,
            product_code_normalized=code_normalized,
            name=value_to_text(payload.get('name')),
            description=value_to_text(payload.get('description')),
            category=value_to_text(payload.get('category')),
            length_mm=payload.get('length_mm'),
            width_mm=payload.get('width_mm'),
            height_mm=payload.get('height_mm'),
            cubic_m3=payload.get('cubic_m3'),
            quantity=payload.get('quantity'),
            weight_kg=payload.get('weight_kg'),
            pallet=payload.get('pallet'),
            comment=value_to_text(payload.get('comment')),
            source_status=value_to_text(payload.get('source_status')),
            raw_data={
                'source': 'APPROVED_REPAIR',
                'rejected_row_id': row.pk,
                'original_column_count': row.column_count,
                'original_raw_values': row.raw_values,
                'approved_values': saved_payload,
            },
            validation_errors=[],
        )

        row.proposed_data = saved_payload
        row.review_note = note
        row.repair_status = 'APPROVED'
        row.reviewed_by = actor if getattr(actor, 'is_authenticated', False) else None
        row.reviewed_at = timezone.now()
        row.staged_row = staged
        row.save(update_fields=[
            'proposed_data', 'review_note', 'repair_status', 'reviewed_by',
            'reviewed_at', 'staged_row',
        ])
        _refresh_repair_summary(row.external_file)
        create_audit_event(
            event_type='PRODUCT_SOURCE_REPAIR_APPROVED',
            message=(
                f'Product source row {row.source_row_number} approved into '
                f'reference staging as SKU {code_normalized}.'
            ),
            actor=actor,
            client=row.external_file.client,
            external_file=row.external_file,
            metadata={
                'rejected_row_id': row.pk,
                'staged_row_id': staged.pk,
                'source_row_number': row.source_row_number,
                'product_code': code_normalized,
                'approved_values': saved_payload,
                'review_note': note,
                'operational_tables_updated': False,
            },
            request=request,
        )
        return row

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from apps.imports.models import ProductSourceRow
from apps.imports.services.xlsx_reader import normalize_product_sku
from apps.products.models import Product


ZERO = Decimal('0')


def _normalise_text(value):
    return str(value or '').strip()


def _decimal(value):
    return ZERO if value is None else Decimal(value)


def _source_metres(value):
    return _decimal(value) / Decimal('1000')


def _different(left, right):
    return _decimal(left) != _decimal(right)


def _source_values(source):
    return {
        'name': source.name,
        'description': source.description,
        'length_m': _source_metres(source.length_mm),
        'width_m': _source_metres(source.width_mm),
        'height_m': _source_metres(source.height_mm),
        'weight_kg': source.weight_kg,
        'cubic_m3': source.cubic_m3,
        'quantity': source.quantity,
        'pallet': source.pallet,
        'comment': source.comment,
        'source_status': source.source_status,
    }


def _operational_values(product):
    if product is None:
        return {}
    return {
        'name': product.name,
        'description': product.description,
        'length_m': product.length_m,
        'width_m': product.width_m,
        'height_m': product.height_m,
        'weight_kg': product.weight_kg,
        'cubic_m3': product.cubic_m3,
        'freight_type': product.freight_type,
        'active': product.active,
    }


def _matched_row(source, product, duplicate_count):
    source_values = _source_values(source)
    operational_values = _operational_values(product)
    warnings = []
    changed_fields = []

    source_dimensions = (
        source_values['length_m'], source_values['width_m'], source_values['height_m']
    )
    operational_dimensions = (
        product.length_m, product.width_m, product.height_m
    )
    if all(value == ZERO for value in source_dimensions) and any(
        value > ZERO for value in operational_dimensions
    ):
        warnings.append('SOURCE_DIMENSIONS_ZERO')
    if source_dimensions != operational_dimensions:
        changed_fields.append('dimensions')
        warnings.append('DIMENSIONS_DIFFERENT')
    if _different(source.weight_kg, product.weight_kg):
        changed_fields.append('weight')
        warnings.append('WEIGHT_DIFFERENT')
    if _different(source.cubic_m3, product.cubic_m3):
        changed_fields.append('cubic')
        warnings.append('CUBIC_DIFFERENT')
    if _normalise_text(source.name) != _normalise_text(product.name):
        changed_fields.append('name')
    if _normalise_text(source.description) != _normalise_text(product.description):
        changed_fields.append('description')
    if duplicate_count > 1:
        warnings.append('DUPLICATE_SOURCE_SKU')

    return {
        'source': source,
        'product': product,
        'sku': source.product_code_normalized,
        'source_row_number': source.source_row_number,
        'status': 'DUPLICATE_SOURCE' if duplicate_count > 1 else (
            'DIFFERENT' if changed_fields else 'SAME'
        ),
        'changed_fields': changed_fields,
        'warnings': warnings,
        'source_values': source_values,
        'operational_values': operational_values,
    }


def build_product_reconciliation(external_file):
    """Compare reference staging against Product without changing either table."""
    source_rows = list(
        ProductSourceRow.objects.filter(external_file=external_file)
        .order_by('source_row_number')
    )
    products = {
        normalize_product_sku(product.sku): product
        for product in Product.objects.filter(client=external_file.client).order_by('sku')
    }
    source_counts = Counter(row.product_code_normalized for row in source_rows)
    source_skus = set(source_counts)
    rows = []

    for source in source_rows:
        product = products.get(source.product_code_normalized)
        if product is None:
            rows.append({
                'source': source,
                'product': None,
                'sku': source.product_code_normalized,
                'source_row_number': source.source_row_number,
                'status': 'DUPLICATE_SOURCE' if source_counts[source.product_code_normalized] > 1 else 'SOURCE_ONLY',
                'changed_fields': [],
                'warnings': (
                    ['DUPLICATE_SOURCE_SKU']
                    if source_counts[source.product_code_normalized] > 1
                    else ['FREIGHT_TYPE_REQUIRED']
                ),
                'source_values': _source_values(source),
                'operational_values': {},
            })
        else:
            rows.append(_matched_row(
                source, product, source_counts[source.product_code_normalized]
            ))

    for normalised_sku, product in products.items():
        if normalised_sku not in source_skus:
            rows.append({
                'source': None,
                'product': product,
                'sku': product.sku,
                'source_row_number': None,
                'status': 'OPERATIONAL_ONLY',
                'changed_fields': [],
                'warnings': ['NOT_IN_SOURCE'],
                'source_values': {},
                'operational_values': _operational_values(product),
            })

    counts = Counter(row['status'] for row in rows)
    summary = {
        'source_rows': len(source_rows),
        'operational_products': len(products),
        'same': counts['SAME'],
        'different': counts['DIFFERENT'],
        'source_only': counts['SOURCE_ONLY'],
        'operational_only': counts['OPERATIONAL_ONLY'],
        'duplicate_source': counts['DUPLICATE_SOURCE'],
        'pending_rejected': external_file.product_rejected_rows.exclude(
            repair_status='APPROVED'
        ).count(),
        'operational_tables_updated': False,
    }
    return rows, summary

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.imports.models import (
    ProductReconciliationDecision,
    ProductReconciliationRule,
)
from apps.imports.services.audit import create_audit_event
from apps.imports.services.product_reconciliation import build_product_reconciliation


RECONCILABLE_FIELDS = (
    'name', 'description', 'dimensions', 'weight', 'cubic', 'freight_type',
)
FIELD_AUTHORITIES = {'SOURCE', 'OPERATIONAL', 'CUSTOM', 'NO_CHANGE'}

PRESETS = {
    'KEEP_OPERATIONAL_ALL': {
        field: 'OPERATIONAL' for field in RECONCILABLE_FIELDS
    },
    'KEEP_PHYSICAL_USE_SOURCE_TEXT': {
        'name': 'SOURCE',
        'description': 'SOURCE',
        'dimensions': 'OPERATIONAL',
        'weight': 'OPERATIONAL',
        'cubic': 'OPERATIONAL',
        'freight_type': 'SOURCE',
    },
    'USE_SOURCE_SAFE': {
        field: 'SOURCE' for field in RECONCILABLE_FIELDS
    },
    'REFERENCE_ONLY': {
        field: 'NO_CHANGE' for field in RECONCILABLE_FIELDS
    },
}


class ProductReconciliationWorkspaceError(Exception):
    pass


def derive_freight_type_from_pallet(value):
    """Return the current Chat.Calc C/P proposal and an optional review warning."""
    if value is None or str(value).strip() == '':
        return None, 'PALLET_VALUE_MISSING'
    try:
        pallet = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None, 'PALLET_VALUE_INVALID'
    if not pallet.is_finite():
        return None, 'PALLET_VALUE_INVALID'
    if pallet < 0:
        return None, 'PALLET_VALUE_NEGATIVE'
    return ('C' if pallet == 0 else 'P'), None


def apply_freight_type_rule(row):
    source = row['source_values']
    if not row.get('source'):
        source['freight_type'] = None
        row['freight_type_review_required'] = False
        return row

    proposed, warning = derive_freight_type_from_pallet(source.get('pallet'))
    source['freight_type'] = proposed
    row['freight_type_review_required'] = warning is not None
    if warning:
        if warning not in row['warnings']:
            row['warnings'].append(warning)
        if 'FREIGHT_TYPE_REQUIRED' not in row['warnings']:
            row['warnings'].append('FREIGHT_TYPE_REQUIRED')
        return row

    if 'FREIGHT_TYPE_REQUIRED' in row['warnings']:
        row['warnings'].remove('FREIGHT_TYPE_REQUIRED')
    current = row['operational_values'].get('freight_type')
    if current and proposed != current:
        if 'freight_type' not in row['changed_fields']:
            row['changed_fields'].append('freight_type')
        if 'FREIGHT_TYPE_DIFFERENT' not in row['warnings']:
            row['warnings'].append('FREIGHT_TYPE_DIFFERENT')
        if row['status'] == 'SAME':
            row['status'] = 'DIFFERENT'
    return row


def classify_reconciliation_row(row):
    if row['status'] == 'OPERATIONAL_ONLY':
        return 'OPERATIONAL_ONLY'
    if row['status'] == 'DUPLICATE_SOURCE':
        return 'DUPLICATE_SOURCE'
    if row.get('freight_type_review_required'):
        return 'FREIGHT_TYPE_REVIEW'
    if row['status'] == 'SOURCE_ONLY':
        return 'SOURCE_ONLY'
    if row['status'] == 'SAME':
        return 'SAME'
    if 'SOURCE_DIMENSIONS_ZERO' in row['warnings']:
        return 'SOURCE_DIMENSIONS_ZERO'
    changed = set(row['changed_fields'])
    if changed == {'freight_type'}:
        return 'FREIGHT_TYPE_DIFFERENCES'
    if changed and changed.issubset({'name', 'description'}):
        return 'TEXT_ONLY'
    if changed.intersection({'dimensions', 'weight', 'cubic'}):
        return 'PHYSICAL_DIFFERENCES'
    return 'OTHER_DIFFERENCES'


def decorate_reconciliation(rows, external_file):
    decisions = {
        decision.product_code_normalized: decision
        for decision in ProductReconciliationDecision.objects.filter(
            external_file=external_file
        )
    }
    for row in rows:
        row['group_key'] = classify_reconciliation_row(row)
        row['decision'] = decisions.get(row['sku'])
    return rows


def reconciliation_group_counts(rows):
    counts = {
        'ALL_DIFFERENCES': 0,
        'SOURCE_DIMENSIONS_ZERO': 0,
        'FREIGHT_TYPE_REVIEW': 0,
        'FREIGHT_TYPE_DIFFERENCES': 0,
        'TEXT_ONLY': 0,
        'PHYSICAL_DIFFERENCES': 0,
        'OTHER_DIFFERENCES': 0,
        'SOURCE_ONLY': 0,
        'OPERATIONAL_ONLY': 0,
        'DUPLICATE_SOURCE': 0,
        'SAME': 0,
    }
    for row in rows:
        key = row['group_key']
        counts[key] = counts.get(key, 0) + 1
        if row['status'] in {'DIFFERENT', 'DUPLICATE_SOURCE'}:
            counts['ALL_DIFFERENCES'] += 1
    return counts


def rows_for_group(rows, group_key):
    if group_key == 'ALL':
        return list(rows)
    if group_key == 'ALL_DIFFERENCES':
        return [row for row in rows if row['status'] in {'DIFFERENT', 'DUPLICATE_SOURCE'}]
    return [row for row in rows if row['group_key'] == group_key]


def build_workspace(external_file):
    rows, summary = build_product_reconciliation(external_file)
    for row in rows:
        apply_freight_type_rule(row)
    counts = Counter(row['status'] for row in rows)
    summary.update({
        'same': counts['SAME'],
        'different': counts['DIFFERENT'],
        'source_only': counts['SOURCE_ONLY'],
        'operational_only': counts['OPERATIONAL_ONLY'],
        'duplicate_source': counts['DUPLICATE_SOURCE'],
        'freight_type_review_required': sum(
            1 for row in rows if row.get('freight_type_review_required')
        ),
    })
    decorate_reconciliation(rows, external_file)
    summary['group_counts'] = reconciliation_group_counts(rows)
    summary['draft_decisions'] = sum(1 for row in rows if row.get('decision'))
    summary['pending_decisions'] = sum(
        1
        for row in rows
        if row['status'] != 'SAME' and not row.get('decision')
    )
    return rows, summary


def field_decisions_from_preset(preset):
    try:
        return dict(PRESETS[preset])
    except KeyError as exc:
        raise ProductReconciliationWorkspaceError('Select a valid bulk decision.') from exc


def validate_field_decisions(field_decisions, custom_values=None):
    decisions = {}
    for field in RECONCILABLE_FIELDS:
        authority = str((field_decisions or {}).get(field) or 'NO_CHANGE').upper()
        if authority not in FIELD_AUTHORITIES:
            raise ProductReconciliationWorkspaceError(
                f'Invalid authority {authority} for {field}.'
            )
        decisions[field] = authority

    custom_values = dict(custom_values or {})
    if decisions['name'] == 'CUSTOM' and not str(custom_values.get('name') or '').strip():
        raise ProductReconciliationWorkspaceError('A custom name is required.')
    if decisions['description'] == 'CUSTOM' and not str(
        custom_values.get('description') or ''
    ).strip():
        raise ProductReconciliationWorkspaceError('A custom description is required.')
    if decisions['freight_type'] == 'CUSTOM':
        freight_type = str(custom_values.get('freight_type') or '').strip().upper()
        if freight_type not in {'C', 'P'}:
            raise ProductReconciliationWorkspaceError(
                'Select C (Case) or P (Pallet) as the custom freight type.'
            )
        custom_values['freight_type'] = freight_type

    decimal_keys = {
        'dimensions': ('length_m', 'width_m', 'height_m'),
        'weight': ('weight_kg',),
        'cubic': ('cubic_m3',),
    }
    for field, keys in decimal_keys.items():
        if decisions[field] != 'CUSTOM':
            continue
        for key in keys:
            value = custom_values.get(key)
            try:
                decimal = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ProductReconciliationWorkspaceError(
                    f'A valid custom value is required for {key}.'
                ) from exc
            if decimal < 0:
                raise ProductReconciliationWorkspaceError(
                    f'The custom value for {key} cannot be negative.'
                )
            custom_values[key] = str(decimal)
    return decisions, custom_values


def _row_map(external_file):
    rows, _summary = build_workspace(external_file)
    return {row['sku']: row for row in rows}


@transaction.atomic
def save_product_reconciliation_decisions(
    external_file,
    *,
    skus,
    field_decisions,
    custom_values=None,
    notes='',
    actor=None,
    request=None,
):
    if external_file.file_type != 'PRODUCTS' or external_file.status != 'VALIDATED':
        raise ProductReconciliationWorkspaceError(
            'Only a validated Product source can be reconciled.'
        )
    field_decisions, custom_values = validate_field_decisions(
        field_decisions,
        custom_values,
    )
    rows = _row_map(external_file)
    normalised_skus = list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
    if not normalised_skus:
        raise ProductReconciliationWorkspaceError('Select at least one Product row.')

    saved = []
    for sku in normalised_skus:
        row = rows.get(sku)
        if row is None:
            raise ProductReconciliationWorkspaceError(
                f'Product {sku} is not part of this reconciliation.'
            )
        if row['status'] == 'SAME' and not row.get('freight_type_review_required'):
            raise ProductReconciliationWorkspaceError(
                f'Product {sku} has no differences to reconcile.'
            )
        if (
            field_decisions['freight_type'] == 'SOURCE'
            and row['source_values'].get('freight_type') not in {'C', 'P'}
        ):
            raise ProductReconciliationWorkspaceError(
                f'Product {sku} has no valid pallet value. Select C or P manually.'
            )
        decision, _created = ProductReconciliationDecision.objects.update_or_create(
            external_file=external_file,
            product_code_normalized=sku,
            defaults={
                'source_row_number': row['source_row_number'],
                'row_status': row['status'],
                'group_key': row['group_key'],
                'field_decisions': field_decisions,
                'custom_values': custom_values,
                'decision_status': 'DRAFT',
                'notes': str(notes or '').strip(),
                'reviewed_by': actor,
            },
        )
        saved.append(decision)

    create_audit_event(
        event_type='PRODUCT_RECONCILIATION_DRAFT_SAVED',
        message=f'{len(saved)} Product reconciliation draft decision(s) saved.',
        actor=actor,
        client=external_file.client,
        external_file=external_file,
        metadata={
            'decision_count': len(saved),
            'sample_skus': [
                decision.product_code_normalized for decision in saved[:100]
            ],
            'sku_sample_truncated': len(saved) > 100,
            'field_decisions': field_decisions,
            'operational_tables_updated': False,
        },
        request=request,
    )
    return saved


@transaction.atomic
def save_reconciliation_rule(
    external_file,
    *,
    name,
    group_key,
    field_decisions,
    actor=None,
    request=None,
):
    name = str(name or '').strip()
    if not name:
        raise ProductReconciliationWorkspaceError('Enter a name for the reusable rule.')
    field_decisions, _custom_values = validate_field_decisions(field_decisions)
    if 'CUSTOM' in field_decisions.values():
        raise ProductReconciliationWorkspaceError(
            'Custom per-product values cannot be saved as a reusable rule.'
        )
    rule, _created = ProductReconciliationRule.objects.update_or_create(
        client=external_file.client,
        name=name,
        defaults={
            'group_key': group_key,
            'field_decisions': field_decisions,
            'active': True,
            'created_by': actor,
        },
    )
    create_audit_event(
        event_type='PRODUCT_RECONCILIATION_RULE_SAVED',
        message=f'Product reconciliation rule {rule.name} saved.',
        actor=actor,
        client=external_file.client,
        external_file=external_file,
        metadata={
            'rule_id': rule.pk,
            'group_key': rule.group_key,
            'field_decisions': rule.field_decisions,
            'operational_tables_updated': False,
        },
        request=request,
    )
    return rule


def apply_rule_as_draft(external_file, *, rule, rows, actor=None, request=None):
    if rule.client_id != external_file.client_id or not rule.active:
        raise ProductReconciliationWorkspaceError('The selected rule is not available.')
    targets = rows_for_group(rows, rule.group_key)
    return save_product_reconciliation_decisions(
        external_file,
        skus=[row['sku'] for row in targets],
        field_decisions=rule.field_decisions,
        actor=actor,
        request=request,
        notes=f'Proposed by reusable rule: {rule.name}',
    )


def _pick(authority, source_value, operational_value, custom_value):
    if authority == 'SOURCE':
        return source_value
    if authority == 'OPERATIONAL':
        return operational_value
    if authority == 'CUSTOM':
        return custom_value
    return operational_value if operational_value not in (None, '') else source_value


def preview_decision(row, decision):
    source = row['source_values']
    operational = row['operational_values']
    authorities = decision.field_decisions
    custom = decision.custom_values
    proposed = {
        'name': _pick(authorities['name'], source.get('name'), operational.get('name'), custom.get('name')),
        'description': _pick(
            authorities['description'],
            source.get('description'),
            operational.get('description'),
            custom.get('description'),
        ),
        'length_m': _pick(
            authorities['dimensions'],
            source.get('length_m'),
            operational.get('length_m'),
            custom.get('length_m'),
        ),
        'width_m': _pick(
            authorities['dimensions'],
            source.get('width_m'),
            operational.get('width_m'),
            custom.get('width_m'),
        ),
        'height_m': _pick(
            authorities['dimensions'],
            source.get('height_m'),
            operational.get('height_m'),
            custom.get('height_m'),
        ),
        'weight_kg': _pick(
            authorities['weight'],
            source.get('weight_kg'),
            operational.get('weight_kg'),
            custom.get('weight_kg'),
        ),
        'cubic_m3': _pick(
            authorities['cubic'],
            source.get('cubic_m3'),
            operational.get('cubic_m3'),
            custom.get('cubic_m3'),
        ),
        'freight_type': _pick(
            authorities.get(
                'freight_type',
                'SOURCE' if source.get('freight_type') in {'C', 'P'} else 'OPERATIONAL',
            ),
            source.get('freight_type'),
            operational.get('freight_type'),
            custom.get('freight_type'),
        ),
    }
    return {
        'row': row,
        'decision': decision,
        'proposed_values': proposed,
        'operational_update_available': False,
    }

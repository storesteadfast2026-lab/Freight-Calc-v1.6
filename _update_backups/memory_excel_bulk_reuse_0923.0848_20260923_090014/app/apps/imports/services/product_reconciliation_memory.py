from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.dateparse import parse_datetime

from apps.imports.models import (
    ExternalDataCorrectionMemory,
    ProductReconciliationDecision,
    ProductSourceRow,
)
from apps.imports.services.audit import create_audit_event
from apps.imports.services.correction_memory import (
    canonical_fingerprint,
    mark_correction_memories_used,
    remember_correction,
)


PRODUCT_RECONCILIATION_MEMORY = 'PRODUCT_RECONCILIATION'
MEMORY_FIELDS = (
    'name', 'description', 'length_m', 'width_m', 'height_m',
    'weight_kg', 'cubic_m3', 'freight_type',
)


class ProductReconciliationMemoryError(Exception):
    pass


def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def product_memory_source_data(row):
    """Stable source-only signature; operational values never affect exact matching."""
    source = row.get('source')
    if source is None:
        return {
            'schema': 1,
            'sku': row['sku'],
            'source_present': False,
        }
    return {
        'schema': 1,
        'sku': row['sku'],
        'source_present': True,
        'source': {
            'name': source.name,
            'description': source.description,
            'category': source.category,
            'length_mm': _json_value(source.length_mm),
            'width_mm': _json_value(source.width_mm),
            'height_mm': _json_value(source.height_mm),
            'weight_kg': _json_value(source.weight_kg),
            'cubic_m3': _json_value(source.cubic_m3),
            'quantity': _json_value(source.quantity),
            'pallet': _json_value(source.pallet),
            'comment': source.comment,
            'source_status': source.source_status,
        },
    }


def _approved_values(values):
    if not values:
        return None
    return {field: _json_value(values.get(field)) for field in MEMORY_FIELDS}


def attach_product_reconciliation_memory(rows, external_file):
    """Decorate rows without N+1 queries and return transversal memory counts."""
    memories = list(
        ExternalDataCorrectionMemory.objects.filter(
            workflow_key=PRODUCT_RECONCILIATION_MEMORY,
            client=external_file.client,
            is_active=True,
        )
        .select_related('approved_by', 'origin_external_file')
        .order_by('record_key', '-approved_at')
    )
    by_fingerprint = {memory.source_fingerprint: memory for memory in memories}
    by_record = defaultdict(list)
    for memory in memories:
        by_record[memory.record_key].append(memory)

    counts = {'EXACT': 0, 'SOURCE_CHANGED': 0, 'NONE': 0}
    for row in rows:
        fingerprint = canonical_fingerprint(product_memory_source_data(row))
        memory = by_fingerprint.get(fingerprint)
        if memory is not None:
            state = 'EXACT'
        else:
            candidates = by_record.get(row['sku']) or []
            memory = candidates[0] if candidates else None
            state = 'SOURCE_CHANGED' if memory is not None else 'NONE'
        row['memory_state'] = state
        row['memory'] = memory
        row['memory_source_fingerprint'] = fingerprint
        row['memory_approved_values'] = (
            (memory.approved_data or {}).get('approved_values') if memory else None
        )
        counts[state] += 1
    return counts


def _decimal_equal(left, right):
    if left in (None, '') and right in (None, ''):
        return True
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return str(left or '').strip() == str(right or '').strip()


def _text_equal(left, right):
    return str(left or '').strip() == str(right or '').strip()


def _authority(desired, source, operational, *, decimal=False):
    equal = _decimal_equal if decimal else _text_equal
    if equal(desired, operational):
        return 'OPERATIONAL'
    if equal(desired, source):
        return 'SOURCE'
    return 'CUSTOM'


def decision_payload_from_memory(row, memory):
    approved = dict(memory.approved_data or {})
    row_action = str(approved.get('row_action') or 'UPDATE').upper()
    if row_action == 'KEEP':
        return {'row_action': 'KEEP', 'field_decisions': {}, 'custom_values': {}}
    if row_action == 'DELETE':
        return {
            'row_action': 'DELETE',
            'field_decisions': {
                field: 'NO_CHANGE'
                for field in ('name', 'description', 'dimensions', 'weight', 'cubic', 'freight_type')
            },
            'custom_values': {},
        }

    desired = dict(approved.get('approved_values') or {})
    if not desired:
        raise ProductReconciliationMemoryError(
            f'{row["sku"]}: previous memory does not contain approved Product values.'
        )
    source = row['source_values']
    operational = row['operational_values']
    field_decisions = {
        'name': _authority(desired.get('name'), source.get('name'), operational.get('name')),
        'description': _authority(
            desired.get('description'), source.get('description'), operational.get('description')
        ),
        'weight': _authority(
            desired.get('weight_kg'), source.get('weight_kg'), operational.get('weight_kg'),
            decimal=True,
        ),
        'cubic': _authority(
            desired.get('cubic_m3'), source.get('cubic_m3'), operational.get('cubic_m3'),
            decimal=True,
        ),
        'freight_type': _authority(
            desired.get('freight_type'),
            source.get('freight_type'),
            operational.get('freight_type'),
        ),
    }
    desired_dimensions = tuple(desired.get(key) for key in ('length_m', 'width_m', 'height_m'))
    source_dimensions = tuple(source.get(key) for key in ('length_m', 'width_m', 'height_m'))
    operational_dimensions = tuple(
        operational.get(key) for key in ('length_m', 'width_m', 'height_m')
    )
    if all(_decimal_equal(a, b) for a, b in zip(desired_dimensions, operational_dimensions)):
        field_decisions['dimensions'] = 'OPERATIONAL'
    elif all(_decimal_equal(a, b) for a, b in zip(desired_dimensions, source_dimensions)):
        field_decisions['dimensions'] = 'SOURCE'
    else:
        field_decisions['dimensions'] = 'CUSTOM'

    custom_values = {
        'name': desired.get('name'),
        'description': desired.get('description'),
        'length_m': desired.get('length_m'),
        'width_m': desired.get('width_m'),
        'height_m': desired.get('height_m'),
        'weight_kg': desired.get('weight_kg'),
        'cubic_m3': desired.get('cubic_m3'),
        'freight_type': desired.get('freight_type'),
    }
    return {
        'row_action': 'UPDATE',
        'field_decisions': field_decisions,
        'custom_values': custom_values,
    }


def _save_memory_draft(external_file, row, memory, actor):
    from apps.imports.services.product_reconciliation_workspace import validate_field_decisions

    payload = decision_payload_from_memory(row, memory)
    if payload['row_action'] == 'KEEP':
        return None
    if payload['row_action'] == 'DELETE' and row['status'] != 'OPERATIONAL_ONLY':
        raise ProductReconciliationMemoryError(
            f'{row["sku"]}: previous removal is no longer compatible with this Source.'
        )
    if payload['row_action'] == 'UPDATE' and (not row.get('source') or not row.get('product')):
        raise ProductReconciliationMemoryError(
            f'{row["sku"]}: previous update requires both Source and operational Product.'
        )
    decisions, custom = validate_field_decisions(
        payload['field_decisions'], payload['custom_values']
    )
    decision, _created = ProductReconciliationDecision.objects.update_or_create(
        external_file=external_file,
        product_code_normalized=row['sku'],
        defaults={
            'source_row_number': row['source_row_number'],
            'row_status': row['status'],
            'group_key': row['group_key'],
            'field_decisions': decisions,
            'custom_values': custom,
            'row_action': payload['row_action'],
            'decision_status': 'DRAFT',
            'notes': (
                f'Reused approved reconciliation memory #{memory.pk}. '
                f'{memory.approval_note}'
            ).strip(),
            'reviewed_by': actor,
            'applied_by': None,
            'applied_at': None,
            'apply_batch_id': '',
        },
    )
    return decision


@transaction.atomic
def prepare_exact_memory_drafts(external_file, *, actor=None, request=None):
    """Option 1A: idempotently prepare exact previous solutions as drafts."""
    from apps.imports.services.product_reconciliation_workspace import build_workspace

    rows, _summary = build_workspace(external_file)
    existing = set(
        ProductReconciliationDecision.objects.filter(external_file=external_file)
        .values_list('product_code_normalized', flat=True)
    )
    prepared = []
    used_memory_ids = []
    for row in rows:
        memory = row.get('memory')
        if (
            row.get('memory_state') != 'EXACT'
            or memory is None
            or row['sku'] in existing
            or row['status'] == 'SAME'
        ):
            continue
        decision = _save_memory_draft(external_file, row, memory, actor)
        if decision is not None:
            prepared.append(decision)
            used_memory_ids.append(memory.pk)
    mark_correction_memories_used(used_memory_ids)
    if prepared:
        create_audit_event(
            event_type='PRODUCT_RECONCILIATION_MEMORY_DRAFTS_PREPARED',
            message=f'{len(prepared)} exact previous Product solution(s) prepared as drafts.',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            metadata={
                'decision_count': len(prepared),
                'memory_ids': used_memory_ids[:500],
                'exact_source_match_required': True,
                'operational_tables_updated': False,
            },
            request=request,
        )
    return prepared


@transaction.atomic
def reuse_product_memories(external_file, *, skus, actor=None, request=None):
    """Explicit reuse for selected exact or source-changed rows."""
    from apps.imports.services.product_reconciliation_workspace import build_workspace

    rows, _summary = build_workspace(external_file)
    row_map = {row['sku']: row for row in rows}
    selected = list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
    if not selected:
        raise ProductReconciliationMemoryError('Select at least one Product row.')
    prepared = []
    used_memory_ids = []
    for sku in selected:
        row = row_map.get(sku)
        if row is None or row.get('memory') is None:
            raise ProductReconciliationMemoryError(f'{sku}: no previous solution is available.')
        decision = _save_memory_draft(external_file, row, row['memory'], actor)
        if decision is not None:
            prepared.append(decision)
            used_memory_ids.append(row['memory'].pk)
    mark_correction_memories_used(used_memory_ids)
    create_audit_event(
        event_type='PRODUCT_RECONCILIATION_MEMORY_REUSED',
        message=f'{len(prepared)} previous Product solution(s) explicitly reused as drafts.',
        actor=actor,
        client=external_file.client,
        external_file=external_file,
        metadata={
            'decision_count': len(prepared),
            'memory_ids': used_memory_ids[:500],
            'selected_skus': selected[:500],
            'operational_tables_updated': False,
        },
        request=request,
    )
    return prepared


@transaction.atomic
def adopt_operational_product_memories(
    external_file, *, skus, approval_note, actor=None, request=None
):
    """Option 3A: administrator adopts current operational values as approved memory."""
    from apps.imports.services.product_reconciliation_workspace import build_workspace

    note = str(approval_note or '').strip()
    if not note:
        raise ProductReconciliationMemoryError(
            'A reason is required to adopt current Calculator values as memory.'
        )
    rows, _summary = build_workspace(external_file)
    row_map = {row['sku']: row for row in rows}
    selected = list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
    if not selected:
        raise ProductReconciliationMemoryError('Select at least one Product row.')
    memories = []
    for sku in selected:
        row = row_map.get(sku)
        if row is None or not row.get('product'):
            raise ProductReconciliationMemoryError(
                f'{sku}: only an existing operational Product can be adopted.'
            )
        row_action = 'KEEP' if row['status'] == 'OPERATIONAL_ONLY' else 'UPDATE'
        memory = remember_correction(
            workflow_key=PRODUCT_RECONCILIATION_MEMORY,
            client=external_file.client,
            record_key=sku,
            source_data=product_memory_source_data(row),
            approved_data={
                'schema': 1,
                'row_action': row_action,
                'field_decisions': {
                    field: 'OPERATIONAL'
                    for field in ('name', 'description', 'dimensions', 'weight', 'cubic', 'freight_type')
                },
                'approved_values': _approved_values(row['operational_values']),
                'adopted_operational_state': True,
            },
            approval_note=note,
            origin_external_file=external_file,
            actor=actor,
            request=request,
            create_audit=False,
        )
        memories.append(memory)
    create_audit_event(
        event_type='PRODUCT_RECONCILIATION_MEMORY_ADOPTED',
        message=f'{len(memories)} current operational Product solution(s) adopted as memory.',
        actor=actor,
        client=external_file.client,
        external_file=external_file,
        metadata={
            'memory_ids': [memory.pk for memory in memories][:500],
            'selected_skus': selected[:500],
            'approval_note': note,
            'operational_tables_updated': False,
        },
        request=request,
    )
    return memories


@transaction.atomic
def backfill_applied_product_memories(external_file, *, actor=None, request=None):
    """Record memories for Apply decisions created before this feature was installed."""
    external_file.refresh_from_db(fields=['import_summary'])
    batches = {
        batch.get('batch_id'): batch
        for batch in (
            (external_file.import_summary or {}).get('product_reconciliation_apply_batches') or []
        )
        if batch.get('batch_id') and not batch.get('rolled_back_at')
    }
    decisions = list(
        ProductReconciliationDecision.objects.filter(
            external_file=external_file,
            decision_status='APPLIED',
        ).order_by('product_code_normalized')
    )
    if not decisions:
        return []

    source_by_sku = {
        row.product_code_normalized: row
        for row in ProductSourceRow.objects.filter(external_file=external_file).order_by(
            'product_code_normalized', 'source_row_number'
        )
    }
    created = []
    for decision in decisions:
        batch = batches.get(decision.apply_batch_id)
        if batch is None:
            continue
        change = next(
            (
                item for item in (batch.get('changes') or [])
                if item.get('sku') == decision.product_code_normalized
            ),
            None,
        )
        if change is None:
            continue
        source = source_by_sku.get(decision.product_code_normalized)
        source_data = product_memory_source_data({
            'sku': decision.product_code_normalized,
            'source': source,
        })
        source_fingerprint = canonical_fingerprint(source_data)
        if ExternalDataCorrectionMemory.objects.filter(
            workflow_key=PRODUCT_RECONCILIATION_MEMORY,
            client=external_file.client,
            source_fingerprint=source_fingerprint,
            is_active=True,
        ).exists():
            continue
        memory = remember_correction(
            workflow_key=PRODUCT_RECONCILIATION_MEMORY,
            client=external_file.client,
            record_key=decision.product_code_normalized,
            source_data=source_data,
            approved_data={
                'schema': 1,
                'row_action': decision.row_action,
                'field_decisions': decision.field_decisions,
                'approved_values': _approved_values(change.get('after')),
                'adopted_operational_state': False,
                'apply_batch_id': decision.apply_batch_id,
                'backfilled_from_applied_decision': True,
            },
            approval_note=(
                f'Adopted from previously applied decision #{decision.pk}. '
                f'{decision.notes}'
            ).strip(),
            origin_external_file=external_file,
            actor=decision.applied_by or actor,
            request=request,
            create_audit=False,
        )
        created.append(memory)

    if created:
        create_audit_event(
            event_type='PRODUCT_RECONCILIATION_MEMORY_BACKFILLED',
            message=(
                f'{len(created)} previously applied Product decision(s) adopted as memory.'
            ),
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            metadata={
                'memory_ids': [memory.pk for memory in created][:500],
                'operational_tables_updated': False,
            },
            request=request,
        )
    return created


def remember_applied_product_decision(
    external_file, *, item, after_values, apply_batch_id, actor=None, request=None
):
    row = item['row']
    decision = item['decision']
    source_data = product_memory_source_data(row)
    approved_data = {
        'schema': 1,
        'row_action': decision.row_action,
        'field_decisions': decision.field_decisions,
        'approved_values': _approved_values(after_values),
        'adopted_operational_state': False,
        'apply_batch_id': apply_batch_id,
    }
    source_fingerprint = canonical_fingerprint(source_data)
    existing = ExternalDataCorrectionMemory.objects.filter(
        workflow_key=PRODUCT_RECONCILIATION_MEMORY,
        client=external_file.client,
        source_fingerprint=source_fingerprint,
        is_active=True,
    ).first()
    if existing is not None:
        previous_core = {
            'row_action': (existing.approved_data or {}).get('row_action'),
            'approved_values': (existing.approved_data or {}).get('approved_values'),
        }
        new_core = {
            'row_action': approved_data['row_action'],
            'approved_values': approved_data['approved_values'],
        }
        if canonical_fingerprint(previous_core) == canonical_fingerprint(new_core):
            mark_correction_memories_used([existing.pk])
            return existing
        approved_data['previous_memory'] = {
            'proposal_fingerprint': existing.proposal_fingerprint,
            'approved_data': existing.approved_data,
            'approval_note': existing.approval_note,
            'origin_external_file_id': existing.origin_external_file_id,
            'approved_by_id': existing.approved_by_id,
            'approved_at': existing.approved_at.isoformat(),
            'last_used_at': existing.last_used_at.isoformat() if existing.last_used_at else None,
            'use_count': existing.use_count,
        }
    return remember_correction(
        workflow_key=PRODUCT_RECONCILIATION_MEMORY,
        client=external_file.client,
        record_key=row['sku'],
        source_data=source_data,
        approved_data=approved_data,
        approval_note=decision.notes,
        origin_external_file=external_file,
        actor=actor,
        request=request,
        create_audit=False,
    )


@transaction.atomic
def rollback_product_memories_for_batch(
    external_file, *, apply_batch_id, actor=None, request=None
):
    memories = list(
        ExternalDataCorrectionMemory.objects.select_for_update().filter(
            workflow_key=PRODUCT_RECONCILIATION_MEMORY,
            client=external_file.client,
            approved_data__apply_batch_id=apply_batch_id,
        )
    )
    restored = 0
    deactivated = 0
    for memory in memories:
        previous = (memory.approved_data or {}).get('previous_memory')
        if previous:
            memory.proposal_fingerprint = previous['proposal_fingerprint']
            memory.approved_data = previous['approved_data']
            memory.approval_note = previous['approval_note']
            memory.origin_external_file_id = previous['origin_external_file_id']
            memory.approved_by_id = previous['approved_by_id']
            memory.approved_at = parse_datetime(previous['approved_at'])
            memory.last_used_at = (
                parse_datetime(previous['last_used_at'])
                if previous.get('last_used_at') else None
            )
            memory.use_count = previous['use_count']
            memory.is_active = True
            memory.save(update_fields=[
                'proposal_fingerprint', 'approved_data', 'approval_note',
                'origin_external_file', 'approved_by', 'approved_at',
                'last_used_at', 'use_count', 'is_active',
            ])
            restored += 1
        else:
            memory.is_active = False
            memory.save(update_fields=['is_active'])
            deactivated += 1
    if memories:
        create_audit_event(
            event_type='PRODUCT_RECONCILIATION_MEMORY_ROLLED_BACK',
            message=(
                f'{restored} previous Product memory value(s) restored and '
                f'{deactivated} new memory value(s) deactivated.'
            ),
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            metadata={
                'apply_batch_id': apply_batch_id,
                'restored_count': restored,
                'deactivated_count': deactivated,
                'memory_ids': [memory.pk for memory in memories][:500],
                'operational_tables_updated': False,
            },
            request=request,
        )
    return {'restored': restored, 'deactivated': deactivated}

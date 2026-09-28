"""Audited, reversible Product corrections on an already applied Source file."""
from types import SimpleNamespace
from uuid import uuid4
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.imports.models import ProductCorrectionRound, ProductCorrectionDecision, ExternalDataFile
from apps.imports.services.audit import create_audit_event
from apps.imports.services.correction_memory import canonical_fingerprint
from apps.imports.services.product_reconciliation_apply import (
    PRODUCT_FIELDS, _product_snapshot, _snapshot_values, ProductReconciliationApplyBlocked,
)
from apps.imports.services.product_reconciliation_memory import (
    product_memory_source_data, remember_applied_product_decision,
    rollback_product_memories_for_batch,
)
from apps.imports.services.product_reconciliation_workspace import (
    build_workspace, has_active_product_apply, preview_decision, validate_field_decisions,
)
from apps.products.models import Product


class CorrectionRoundError(Exception):
    pass


def _rows(source):
    rows, summary = build_workspace(source)
    return {row['sku']: row for row in rows}, summary


def _snapshot_equal(a, b):
    numeric = {'length_m', 'width_m', 'height_m', 'weight_kg', 'cubic_m3'}
    for key in PRODUCT_FIELDS:
        left, right = a.get(key), b.get(key)
        if key in numeric and left is not None and right is not None:
            if Decimal(str(left)) != Decimal(str(right)):
                return False
        elif str(left) != str(right):
            return False
    return True


def _proposed_changes(row, proposed):
    numeric = {'length_m', 'width_m', 'height_m', 'weight_kg', 'cubic_m3'}
    changes = {}
    for field, value in proposed.items():
        current = getattr(row['product'], field)
        if field in numeric and value is not None and current is not None:
            if Decimal(str(value)) != Decimal(str(current)):
                changes[field] = value
        elif value != current:
            changes[field] = value
    return changes


def is_zero_source_dimensions_candidate(row):
    """Select matched rows with zero Source dimensions, including invalid Calculator dimensions."""
    return bool(
        row.get('status') == 'DIFFERENT' and row.get('source') and row.get('product')
        and all(row['source_values'].get(key) == 0 for key in ('length_m', 'width_m', 'height_m'))
    )


def _valid_operational_dimensions(row):
    try:
        dimensions = (
            Decimal(str(row['operational_values'][key]))
            for key in ('length_m', 'width_m', 'height_m')
        )
        return all(value.is_finite() and value > 0 for value in dimensions)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return False


def _protects_zero_source_dimensions(row, decisions):
    return (
        is_zero_source_dimensions_candidate(row)
        and _valid_operational_dimensions(row)
        and decisions.get('dimensions') == 'OPERATIONAL'
    )


def bulk_dimension_candidates(round_obj, skus, *, row_map=None):
    """Recheck selected SKUs against the round's own Calculator Customer."""
    if round_obj.status != 'DRAFT' or not has_active_product_apply(round_obj.external_file):
        raise CorrectionRoundError('This round is no longer editable.')
    selected = list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
    if not selected:
        raise CorrectionRoundError('Select at least one SKU.')
    rows = row_map if row_map is not None else _rows(round_obj.external_file)[0]
    existing = {decision.sku: decision for decision in round_obj.decisions.filter(sku__in=selected)}
    eligible, excluded = [], []
    for sku in selected:
        row = rows.get(sku)
        if not row or not is_zero_source_dimensions_candidate(row) or row['product'].client_id != round_obj.external_file.client_id:
            excluded.append({'sku': sku, 'reason': 'No matched zero-dimension Source difference for this Calculator Customer.'})
        elif not _valid_operational_dimensions(row):
            excluded.append({'sku': sku, 'reason': 'Current Calculator dimensions must all be greater than zero.'})
        elif existing.get(sku) and existing[sku].field_decisions.get('dimensions') == 'OPERATIONAL':
            excluded.append({'sku': sku, 'reason': 'Current Calculator dimensions are already saved in this round.'})
        else:
            eligible.append(sku)
    return {'eligible': eligible, 'excluded': excluded}


@transaction.atomic
def save_bulk_operational_dimensions(round_id, *, skus, expected_eligible, notes, actor=None, request=None):
    round_obj = ProductCorrectionRound.objects.select_for_update().select_related('external_file').get(pk=round_id)
    notes = str(notes or '').strip()
    if not notes:
        raise CorrectionRoundError('Enter a reason for keeping current Calculator dimensions.')
    rows, _ = _rows(round_obj.external_file)
    candidates = bulk_dimension_candidates(round_obj, skus, row_map=rows)
    if candidates['eligible'] != list(expected_eligible):
        raise CorrectionRoundError('The selection changed since Preview. Review the eligible SKUs again.')
    if not candidates['eligible']:
        raise CorrectionRoundError('No eligible SKUs remain. Review the selection again.')
    existing = {decision.sku: decision for decision in round_obj.decisions.filter(sku__in=candidates['eligible'])}
    for sku in candidates['eligible']:
        previous = existing.get(sku)
        decisions = dict(previous.field_decisions) if previous else {}
        decisions['dimensions'] = 'OPERATIONAL'
        _save_decision_for_row(
            round_obj, row=rows[sku], field_decisions=decisions,
            custom_values=previous.custom_values if previous else {},
            notes=previous.notes if previous else notes,
            confirm_source_dimensions=previous.confirm_source_dimensions if previous else False,
            actor=actor, request=request,
        )
    create_audit_event(
        event_type='PRODUCT_CORRECTION_BULK_DIMENSIONS_DRAFT_SAVED',
        message=f"{len(candidates['eligible'])} zero-Source dimension decision(s) saved in draft.",
        actor=actor, client=round_obj.external_file.client,
        external_file=round_obj.external_file,
        metadata={'round_id': round_obj.pk, 'included_skus': candidates['eligible'],
                  'excluded_skus': [item['sku'] for item in candidates['excluded']],
                  'operational_tables_updated': False}, request=request,
    )
    return candidates


@transaction.atomic
def start_correction_round(source_id, *, actor=None, request=None):
    source = ExternalDataFile.objects.select_for_update().get(pk=source_id)
    if source.file_type != 'PRODUCTS' or source.status != 'VALIDATED' or not has_active_product_apply(source):
        raise CorrectionRoundError('An applied, validated Product source is required.')
    if ProductCorrectionRound.objects.filter(external_file=source, status='DRAFT').exists():
        raise CorrectionRoundError('Finish or discard the existing draft correction round first.')
    round_obj = ProductCorrectionRound.objects.create(external_file=source, created_by=actor)
    create_audit_event(event_type='PRODUCT_CORRECTION_ROUND_STARTED', message='Product correction round started.',
                       actor=actor, client=source.client, external_file=source,
                       metadata={'round_id': round_obj.pk}, request=request)
    return round_obj


@transaction.atomic
def save_correction_decision(round_id, *, sku, field_decisions, custom_values=None,
                             notes, confirm_source_dimensions=False, actor=None, request=None):
    round_obj = ProductCorrectionRound.objects.select_for_update().select_related('external_file').get(pk=round_id)
    if round_obj.status != 'DRAFT' or not has_active_product_apply(round_obj.external_file):
        raise CorrectionRoundError('This round is no longer editable.')
    rows, _ = _rows(round_obj.external_file)
    return _save_decision_for_row(
        round_obj, row=rows.get(sku), field_decisions=field_decisions,
        custom_values=custom_values, notes=notes,
        confirm_source_dimensions=confirm_source_dimensions,
        actor=actor, request=request,
    )


def _save_decision_for_row(round_obj, *, row, field_decisions, custom_values,
                           notes, confirm_source_dimensions, actor, request):
    notes = str(notes or '').strip()
    if not notes:
        raise CorrectionRoundError('Enter a reason for this later correction.')
    decisions, custom = validate_field_decisions(field_decisions, custom_values)
    if not row or row['status'] != 'DIFFERENT' or not row.get('source') or not row.get('product'):
        raise CorrectionRoundError('Select a matched Product with a remaining difference.')
    sku = row['sku']
    if decisions['dimensions'] == 'SOURCE':
        if 'SOURCE_DIMENSIONS_ZERO' in row['warnings']:
            raise CorrectionRoundError('Source dimensions are zero. Enter reviewed custom dimensions instead.')
        if row.get('dimension_unit_review_required') and not confirm_source_dimensions:
            raise CorrectionRoundError('Confirm the Source dimension units after manual review.')
    if decisions['freight_type'] == 'SOURCE' and row['source_values'].get('freight_type') not in {'C', 'P'}:
        raise CorrectionRoundError('Invalid Source pallet. Choose C or P manually.')
    proposed = preview_decision(row, SimpleNamespace(field_decisions=decisions, custom_values=custom, row_action='UPDATE'))['proposed_values']
    if proposed.get('freight_type') not in {'C', 'P'}:
        raise CorrectionRoundError('C/P must be Case or Pallet.')
    if not _proposed_changes(row, proposed) and not _protects_zero_source_dimensions(row, decisions):
        raise CorrectionRoundError('This decision would not change the operational Product.')
    before = _product_snapshot(row['product'])
    fingerprint = canonical_fingerprint(product_memory_source_data(row))
    decision, _ = ProductCorrectionDecision.objects.update_or_create(
        round=round_obj, sku=sku,
        defaults={'field_decisions': decisions, 'custom_values': custom, 'notes': notes,
                  'confirm_source_dimensions': confirm_source_dimensions,
                  'source_fingerprint': fingerprint, 'before_values': before, 'reviewed_by': actor},
    )
    create_audit_event(event_type='PRODUCT_CORRECTION_DRAFT_SAVED', message=f'{sku}: correction draft saved.',
                       actor=actor, client=round_obj.external_file.client, external_file=round_obj.external_file,
                       metadata={'round_id': round_obj.pk, 'sku': sku, 'operational_tables_updated': False}, request=request)
    return decision


def correction_preview(round_obj):
    rows, summary = _rows(round_obj.external_file)
    if round_obj.status != 'DRAFT':
        historical = []
        for decision in round_obj.decisions.order_by('sku'):
            historical.append({
                'row': rows.get(decision.sku) or {'sku': decision.sku, 'operational_values': {}},
                'decision': decision,
                'proposed_values': decision.after_values,
                'blockers': [],
            })
        return {'items': historical, 'blockers': [], 'can_apply': False,
                'decision_count': len(historical)}
    items, blockers = [], []
    for decision in round_obj.decisions.order_by('sku'):
        row = rows.get(decision.sku)
        errors = []
        if not row or not row.get('product') or not row.get('source'):
            errors.append('Source or Product is missing.')
        else:
            if canonical_fingerprint(product_memory_source_data(row)) != decision.source_fingerprint:
                errors.append('Source row changed after this draft was saved.')
            if not _snapshot_equal(_product_snapshot(row['product']), decision.before_values):
                errors.append('Operational Product changed after this draft was saved.')
            if decision.field_decisions['dimensions'] == 'SOURCE':
                if 'SOURCE_DIMENSIONS_ZERO' in row['warnings']:
                    errors.append('Source dimensions are zero.')
                if row.get('dimension_unit_review_required') and not decision.confirm_source_dimensions:
                    errors.append('Source dimensions require explicit unit confirmation.')
            if decision.field_decisions['freight_type'] == 'SOURCE' and row['source_values'].get('freight_type') not in {'C', 'P'}:
                errors.append('Invalid Source pallet for C/P.')
        item = preview_decision(row, decision) if row and row.get('product') else None
        if item and item['proposed_values'].get('freight_type') not in {'C', 'P'}:
            errors.append('C/P must be Case or Pallet.')
        if item:
            if not _proposed_changes(row, item['proposed_values']) and not _protects_zero_source_dimensions(row, decision.field_decisions):
                errors.append('No operational values would change.')
            if decision.field_decisions.get('dimensions') == 'OPERATIONAL' and is_zero_source_dimensions_candidate(row) and not _valid_operational_dimensions(row):
                errors.append('Current Calculator dimensions must all be greater than zero.')
            item['blockers'] = errors
            items.append(item)
        blockers.extend(f'{decision.sku}: {error}' for error in errors)
    if summary['pending_rejected']:
        blockers.append('Rejected Source rows still require review.')
    return {'items': items, 'blockers': blockers,
            'can_apply': round_obj.status == 'DRAFT' and bool(items) and not blockers,
            'decision_count': round_obj.decisions.count()}


@transaction.atomic
def apply_correction_round(round_id, *, actor=None, request=None):
    round_obj = ProductCorrectionRound.objects.select_for_update().select_related('external_file').get(pk=round_id)
    source = ExternalDataFile.objects.select_for_update().get(pk=round_obj.external_file_id)
    if round_obj.status != 'DRAFT' or not has_active_product_apply(source):
        raise CorrectionRoundError('This round cannot be applied.')
    plan = correction_preview(round_obj)
    if not plan['can_apply']:
        raise CorrectionRoundError('Correction Apply blocked: ' + '; '.join(plan['blockers'] or ['No decisions saved.']))
    batch_id = uuid4().hex
    for item in plan['items']:
        decision = item['decision']
        product = Product.objects.select_for_update().get(pk=item['row']['product'].pk, client=source.client)
        if not _snapshot_equal(_product_snapshot(product), decision.before_values):
            raise CorrectionRoundError(f'{decision.sku}: Product changed during review.')
        changed = _proposed_changes({'product': product}, item['proposed_values'])
        for field, value in changed.items():
            setattr(product, field, value)
        if changed:
            product.save(update_fields=list(changed))
        decision.after_values = _product_snapshot(product)
        decision.save(update_fields=['after_values'])
        remember_applied_product_decision(source, item=item, after_values=decision.after_values,
                                          apply_batch_id=batch_id, actor=actor, request=request)
    round_obj.status = 'APPLIED'
    round_obj.applied_at = timezone.now()
    round_obj.apply_batch_id = batch_id
    round_obj.save(update_fields=['status', 'applied_at', 'apply_batch_id'])
    create_audit_event(event_type='PRODUCT_CORRECTION_ROUND_APPLIED',
                       message=f'{len(plan["items"])} Product correction(s) applied.', actor=actor,
                       client=source.client, external_file=source,
                       metadata={'round_id': round_obj.pk, 'batch_id': batch_id,
                                 'skus': [item['decision'].sku for item in plan['items']]}, request=request)
    return round_obj


@transaction.atomic
def rollback_correction_round(round_id, *, actor=None, request=None):
    round_obj = ProductCorrectionRound.objects.select_for_update().select_related('external_file').get(pk=round_id)
    source = round_obj.external_file
    if round_obj.status != 'APPLIED' or ProductCorrectionRound.objects.filter(
        external_file=source, status='APPLIED', pk__gt=round_obj.pk
    ).exists():
        raise CorrectionRoundError('Only the latest applied correction round can be rolled back.')
    for decision in round_obj.decisions.all():
        product = Product.objects.select_for_update().filter(client=source.client, sku=decision.sku).first()
        if not product or not _snapshot_equal(_product_snapshot(product), decision.after_values):
            raise CorrectionRoundError(f'{decision.sku}: Product changed since Apply; rollback blocked.')
        before = _snapshot_values(decision.before_values)
        changed = _proposed_changes({'product': product}, before)
        for field, value in changed.items():
            setattr(product, field, value)
        if changed:
            product.save(update_fields=list(changed))
    rollback_product_memories_for_batch(source, apply_batch_id=round_obj.apply_batch_id,
                                        actor=actor, request=request)
    round_obj.status = 'ROLLED_BACK'
    round_obj.save(update_fields=['status'])
    create_audit_event(event_type='PRODUCT_CORRECTION_ROUND_ROLLED_BACK',
                       message='Correction round rolled back.', actor=actor, client=source.client,
                       external_file=source, metadata={'round_id': round_obj.pk}, request=request)
    return round_obj

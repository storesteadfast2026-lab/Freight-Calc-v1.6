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
    RECONCILABLE_FIELDS,
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


def _explicitly_keeps_a_difference(row, decisions):
    """A reviewed Calculator value may intentionally leave a Source difference."""
    return any(
        field in row['changed_fields'] and decisions.get(field) == 'OPERATIONAL'
        for field in RECONCILABLE_FIELDS
    )


def corrected_skus_for_source(source):
    return set(
        ProductCorrectionDecision.objects.filter(
            round__external_file=source, round__status='APPLIED',
        ).values_list('sku', flat=True)
    )


@transaction.atomic
def save_inline_correction_decisions(round_id, *, entries, actor=None, request=None):
    """Save selected inline rows into the existing round, with one workspace build."""
    round_obj = ProductCorrectionRound.objects.select_for_update().select_related('external_file').get(pk=round_id)
    if round_obj.status != 'DRAFT' or not has_active_product_apply(round_obj.external_file):
        raise CorrectionRoundError('This round is no longer editable.')
    selected = list(entries)
    if not selected or len({entry['sku'] for entry in selected}) != len(selected):
        raise CorrectionRoundError('Select distinct Product rows to save.')
    rows, _ = _rows(round_obj.external_file)
    corrected = corrected_skus_for_source(round_obj.external_file)
    for entry in selected:
        sku = entry['sku']
        if sku in corrected and not entry.get('allow_reopen'):
            raise CorrectionRoundError(f'{sku}: confirm individual review of this previously corrected SKU.')
        row = rows.get(sku)
        if not row or not row.get('product') or row['product'].client_id != round_obj.external_file.client_id:
            raise CorrectionRoundError(f'{sku}: no matched Product in this Calculator Customer.')
        _save_decision_for_row(
            round_obj, row=row,
            field_decisions=entry['field_decisions'],
            custom_values=entry.get('custom_values'), notes=entry.get('notes'),
            confirm_source_dimensions=entry.get('confirm_source_dimensions', False),
            actor=actor, request=request,
        )
    return len(selected)


def bulk_field_candidates(round_obj, skus, *, field, authority, row_map=None):
    """Preview eligibility for changing one authority, using this source's rows."""
    if field not in RECONCILABLE_FIELDS or authority not in {'SOURCE', 'OPERATIONAL', 'CLEAR'}:
        raise CorrectionRoundError('Choose a valid field and bulk action.')
    if round_obj.status != 'DRAFT' or not has_active_product_apply(round_obj.external_file):
        raise CorrectionRoundError('This round is no longer editable.')
    selected = list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
    if not selected:
        raise CorrectionRoundError('Select at least one Product.')
    rows = row_map if row_map is not None else _rows(round_obj.external_file)[0]
    existing = {d.sku: d for d in round_obj.decisions.filter(sku__in=selected)}
    corrected = corrected_skus_for_source(round_obj.external_file)
    eligible, excluded = [], []
    for sku in selected:
        row, previous = rows.get(sku), existing.get(sku)
        if not row or row.get('status') != 'DIFFERENT' or not row.get('source') or not row.get('product') or row['product'].client_id != round_obj.external_file.client_id:
            reason = 'No matched Product with a remaining difference for this Calculator Customer.'
        elif sku in corrected:
            reason = 'Already corrected in an applied round; use explicit individual review.'
        elif field not in row['changed_fields'] and not previous:
            reason = 'This field does not differ for the selected Product.'
        elif authority == 'CLEAR' and (not previous or previous.field_decisions.get(field, 'NO_CHANGE') == 'NO_CHANGE'):
            reason = 'No saved decision for this field in this round.'
        elif authority != 'CLEAR' and previous and previous.field_decisions.get(field) == authority:
            reason = 'This decision is already saved in this round.'
        elif authority != 'CLEAR' and field not in row['changed_fields']:
            reason = 'This field does not differ for the selected Product.'
        elif field == 'dimensions' and authority == 'SOURCE' and (
            'SOURCE_DIMENSIONS_ZERO' in row['warnings'] or row.get('dimension_unit_review_required')
        ):
            reason = 'Source dimensions require individual review.'
        elif field == 'dimensions' and authority == 'OPERATIONAL' and is_zero_source_dimensions_candidate(row) and not _valid_operational_dimensions(row):
            reason = 'Current Calculator dimensions must all be greater than zero.'
        elif field == 'freight_type' and authority == 'SOURCE' and row['source_values'].get('freight_type') not in {'C', 'P'}:
            reason = 'Source C/P requires individual review.'
        else:
            reason = ''
        if reason:
            excluded.append({'sku': sku, 'reason': reason})
        else:
            eligible.append(sku)
    return {'eligible': eligible, 'excluded': excluded}


@transaction.atomic
def save_bulk_field_decisions(round_id, *, skus, expected_eligible, field,
                              authority, notes, actor=None, request=None):
    """Modify just one field of each existing correction decision."""
    round_obj = ProductCorrectionRound.objects.select_for_update().select_related('external_file').get(pk=round_id)
    notes = str(notes or '').strip()
    if not notes:
        raise CorrectionRoundError('Enter a bulk reason for the selected decision.')
    rows, _ = _rows(round_obj.external_file)
    plan = bulk_field_candidates(round_obj, skus, field=field, authority=authority, row_map=rows)
    if not plan['eligible'] or plan['eligible'] != list(expected_eligible):
        raise CorrectionRoundError('Eligibility changed since Preview. Review the selected SKUs again.')
    previous_by_sku = {d.sku: d for d in round_obj.decisions.filter(sku__in=plan['eligible'])}
    for sku in plan['eligible']:
        previous = previous_by_sku.get(sku)
        decisions = dict(previous.field_decisions) if previous else {}
        decisions[field] = 'NO_CHANGE' if authority == 'CLEAR' else authority
        custom = dict(previous.custom_values) if previous else {}
        if authority != 'CUSTOM':
            keys = {'dimensions': ('length_m', 'width_m', 'height_m'),
                    'weight': ('weight_kg',), 'cubic': ('cubic_m3',)}.get(field, (field,))
            for key in keys:
                custom.pop(key, None)
        remaining = any(decisions.get(key, 'NO_CHANGE') != 'NO_CHANGE' for key in RECONCILABLE_FIELDS)
        if authority == 'CLEAR' and not remaining:
            previous.delete()
            create_audit_event(
                event_type='PRODUCT_CORRECTION_DRAFT_CLEARED',
                message=f'{sku}: correction draft cleared. {notes}',
                actor=actor, client=round_obj.external_file.client,
                external_file=round_obj.external_file,
                metadata={'round_id': round_obj.pk, 'sku': sku, 'field': field,
                          'reason': notes, 'operational_tables_updated': False}, request=request,
            )
            continue
        prior_note = previous.notes if previous else ''
        combined_note = f'{prior_note}\nBulk {field}: {notes}' if prior_note else notes
        _save_decision_for_row(
            round_obj, row=rows[sku], field_decisions=decisions,
            custom_values=custom, notes=combined_note,
            confirm_source_dimensions=previous.confirm_source_dimensions if previous else False,
            actor=actor, request=request,
        )
    create_audit_event(
        event_type='PRODUCT_CORRECTION_BULK_FIELD_DRAFT_SAVED',
        message=f"{len(plan['eligible'])} Product {field} correction decision(s) saved.",
        actor=actor, client=round_obj.external_file.client,
        external_file=round_obj.external_file,
        metadata={'round_id': round_obj.pk, 'field': field, 'authority': authority,
                  'reason': notes, 'included_skus': plan['eligible'],
                  'excluded_skus': [item['sku'] for item in plan['excluded']],
                  'operational_tables_updated': False}, request=request,
    )
    return plan


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
    if not _proposed_changes(row, proposed) and not _explicitly_keeps_a_difference(row, decisions):
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
            if not _proposed_changes(row, item['proposed_values']) and not _explicitly_keeps_a_difference(row, decision.field_decisions):
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

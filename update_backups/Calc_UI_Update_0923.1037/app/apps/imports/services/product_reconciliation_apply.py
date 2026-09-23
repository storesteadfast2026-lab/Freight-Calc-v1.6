from __future__ import annotations

import copy
from uuid import uuid4

from django.db import models, transaction
from django.utils import timezone

from apps.imports.models import ExternalDataFile, ProductReconciliationDecision
from apps.imports.services.audit import create_audit_event
from apps.imports.services.product_reconciliation_workspace import (
    ProductReconciliationWorkspaceError,
    build_workspace,
    preview_decision,
    save_product_reconciliation_decisions,
)
from apps.imports.services.product_reconciliation_memory import (
    remember_applied_product_decision,
    rollback_product_memories_for_batch,
)
from apps.imports.services.xlsx_reader import normalize_product_sku
from apps.products.models import Product, ProductKitComponent
from apps.saved_estimates.models import SavedEstimate


PRODUCT_FIELDS = (
    'name', 'description', 'length_m', 'width_m', 'height_m',
    'weight_kg', 'cubic_m3', 'freight_type', 'active', 'source_row',
)


class ProductReconciliationApplyBlocked(ProductReconciliationWorkspaceError):
    def __init__(self, message, *, plan=None):
        super().__init__(message)
        self.plan = plan or {}


def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _product_snapshot(product):
    return {
        'id': product.pk,
        'client_id': product.client_id,
        'sku': product.sku,
        **{field: _json_value(getattr(product, field)) for field in PRODUCT_FIELDS},
    }


def _snapshot_values(snapshot):
    return {field: snapshot.get(field) for field in PRODUCT_FIELDS}


def _snapshot_contains_sku(snapshot, sku):
    if not isinstance(snapshot, dict):
        return False
    for line in snapshot.get('lines') or []:
        if isinstance(line, dict) and normalize_product_sku(line.get('sku')) == sku:
            return True
    return False


def product_reference_summary(product):
    sku = normalize_product_sku(product.sku)
    kits = ProductKitComponent.objects.filter(client=product.client).filter(
        models.Q(parent_sku__iexact=product.sku)
        | models.Q(component_sku__iexact=product.sku)
    ).count()
    estimates = 0
    for snapshot in SavedEstimate.objects.filter(client=product.client).values_list(
        'input_snapshot', flat=True
    ):
        if _snapshot_contains_sku(snapshot, sku):
            estimates += 1
    return {'kit_components': kits, 'saved_estimates': estimates, 'total': kits + estimates}


def create_recommended_product_drafts(external_file, *, actor=None, request=None):
    """Create the agreed safe baseline: Source text, protected physical values and C/P rule."""
    rows, _summary = build_workspace(external_file)
    matched = [
        row['sku'] for row in rows
        if row['status'] == 'DIFFERENT'
        and not row.get('freight_type_review_required')
        and set(row['changed_fields']).intersection({'name', 'description', 'freight_type'})
    ]
    operational_only = [
        row['sku'] for row in rows if row['status'] == 'OPERATIONAL_ONLY'
    ]
    saved = []
    if matched:
        saved.extend(save_product_reconciliation_decisions(
            external_file,
            skus=matched,
            field_decisions={
                'name': 'SOURCE',
                'description': 'SOURCE',
                'dimensions': 'OPERATIONAL',
                'weight': 'OPERATIONAL',
                'cubic': 'OPERATIONAL',
                'freight_type': 'SOURCE',
            },
            notes=(
                'Recommended initial correction: Source name/description and pallet C/P rule; '
                'retain Calculator physical values pending separate review.'
            ),
            actor=actor,
            request=request,
        ))
    if operational_only:
        saved.extend(save_product_reconciliation_decisions(
            external_file,
            skus=operational_only,
            field_decisions={field: 'NO_CHANGE' for field in (
                'name', 'description', 'dimensions', 'weight', 'cubic', 'freight_type'
            )},
            notes='Recommended controlled removal: SKU is absent from the current Product source.',
            actor=actor,
            request=request,
            row_action='DELETE',
        ))
    return saved


def build_product_apply_plan(external_file_id):
    external_file = ExternalDataFile.objects.get(pk=external_file_id)
    rows, summary = build_workspace(external_file)
    row_map = {row['sku']: row for row in rows}
    items = []
    blockers = []
    decisions = ProductReconciliationDecision.objects.filter(
        external_file=external_file,
        decision_status__in=('DRAFT', 'READY'),
    ).order_by('product_code_normalized')
    for decision in decisions:
        row = row_map.get(decision.product_code_normalized)
        if row is None:
            blockers.append(f'{decision.product_code_normalized}: no longer exists in reconciliation.')
            continue
        item = preview_decision(row, decision)
        item['reference_summary'] = {'kit_components': 0, 'saved_estimates': 0, 'total': 0}
        item_blockers = []
        if decision.row_action == 'DELETE':
            if row['status'] != 'OPERATIONAL_ONLY' or not row.get('product'):
                item_blockers.append('Protected removal is only valid for operational-only Products.')
            else:
                item['reference_summary'] = product_reference_summary(row['product'])
                if item['reference_summary']['total']:
                    item_blockers.append(
                        'Product is referenced by kits or saved quotations and cannot be removed.'
                    )
        else:
            if not row.get('product') or not row.get('source'):
                item_blockers.append('Updates require both Source and operational Product rows.')
            if (
                decision.field_decisions.get('dimensions') == 'SOURCE'
                and ('SOURCE_DIMENSIONS_ZERO' in row['warnings']
                     or row.get('dimension_unit_review_required'))
            ):
                item_blockers.append('Source dimensions require manual unit review before use.')
            if item['proposed_values'].get('freight_type') not in {'C', 'P'}:
                item_blockers.append('C/P must be C or P before Apply.')
        item['blockers'] = item_blockers
        blockers.extend(f'{row["sku"]}: {message}' for message in item_blockers)
        items.append(item)
    if summary['pending_rejected']:
        blockers.append('Rejected Product source rows still require review.')
    return {
        'external_file': external_file,
        'items': items,
        'decision_count': len(items),
        'update_count': sum(item['row_action'] == 'UPDATE' for item in items),
        'delete_count': sum(item['row_action'] == 'DELETE' for item in items),
        'blockers': blockers,
        'can_apply': bool(items) and not blockers,
    }


@transaction.atomic
def apply_product_reconciliation(external_file_id, *, actor=None, request=None):
    external_file = ExternalDataFile.objects.select_for_update().get(pk=external_file_id)
    plan = build_product_apply_plan(external_file.pk)
    if not plan['can_apply']:
        raise ProductReconciliationApplyBlocked(
            'Product changes are blocked. Resolve the listed review items first.',
            plan=plan,
        )
    batch_id = uuid4().hex
    now = timezone.now()
    changes = []
    decision_ids = []
    memory_ids = []
    for item in plan['items']:
        row = item['row']
        decision = item['decision']
        product = Product.objects.select_for_update().get(
            pk=row['product'].pk,
            client=external_file.client,
        )
        before = _product_snapshot(product)
        if decision.row_action == 'DELETE':
            product.delete()
            after = None
        else:
            proposed = item['proposed_values']
            for field in (
                'name', 'description', 'length_m', 'width_m', 'height_m',
                'weight_kg', 'cubic_m3', 'freight_type',
            ):
                setattr(product, field, proposed[field])
            product.source_row = row['source_row_number']
            product.save(update_fields=[
                'name', 'description', 'length_m', 'width_m', 'height_m',
                'weight_kg', 'cubic_m3', 'freight_type', 'source_row',
            ])
            after = _product_snapshot(product)
        changes.append({
            'sku': row['sku'],
            'operation': decision.row_action,
            'before': before,
            'after': after,
        })
        memory = remember_applied_product_decision(
            external_file,
            item=item,
            after_values=after,
            apply_batch_id=batch_id,
            actor=actor,
            request=request,
        )
        memory_ids.append(memory.pk)
        decision_ids.append(decision.pk)

    ProductReconciliationDecision.objects.filter(pk__in=decision_ids).update(
        decision_status='APPLIED',
        applied_by=actor if getattr(actor, 'is_authenticated', False) else None,
        applied_at=now,
        apply_batch_id=batch_id,
    )
    summary = copy.deepcopy(external_file.import_summary or {})
    batches = list(summary.get('product_reconciliation_apply_batches') or [])
    batch = {
        'batch_id': batch_id,
        'applied_at': now.isoformat(),
        'actor_id': getattr(actor, 'pk', None),
        'changes': changes,
        'rolled_back_at': None,
    }
    batches.append(batch)
    summary['product_reconciliation_apply_batches'] = batches
    external_file.import_summary = summary
    external_file.save(update_fields=['import_summary'])
    create_audit_event(
        event_type='PRODUCT_RECONCILIATION_APPLIED',
        message=f'{len(changes)} reviewed Product change(s) applied.',
        actor=actor,
        client=external_file.client,
        external_file=external_file,
        metadata={
            'batch_id': batch_id,
            'update_count': plan['update_count'],
            'delete_count': plan['delete_count'],
            'skus': [change['sku'] for change in changes],
            'correction_memory_ids': memory_ids[:500],
            'correction_memories_recorded': len(memory_ids),
        },
        request=request,
    )
    return batch


def latest_product_apply_batch(external_file):
    for batch in reversed(list(
        (external_file.import_summary or {}).get('product_reconciliation_apply_batches') or []
    )):
        if not batch.get('rolled_back_at'):
            return batch
    return None


@transaction.atomic
def rollback_latest_product_apply(external_file_id, *, actor=None, request=None):
    external_file = ExternalDataFile.objects.select_for_update().get(pk=external_file_id)
    batch = latest_product_apply_batch(external_file)
    if not batch:
        raise ProductReconciliationApplyBlocked('There is no Product Apply batch to roll back.')
    for change in reversed(batch['changes']):
        before = change['before']
        current = Product.objects.filter(
            client=external_file.client,
            sku=before['sku'],
        ).first()
        if change['operation'] == 'DELETE':
            if current:
                raise ProductReconciliationApplyBlocked(
                    f'{before["sku"]}: SKU already exists; rollback cannot recreate it safely.'
                )
            Product.objects.create(
                id=before['id'],
                client_id=before['client_id'],
                sku=before['sku'],
                **_snapshot_values(before),
            )
        else:
            if not current:
                raise ProductReconciliationApplyBlocked(
                    f'{before["sku"]}: Product is missing; rollback cannot restore it safely.'
                )
            for field, value in _snapshot_values(before).items():
                setattr(current, field, value)
            current.save(update_fields=list(PRODUCT_FIELDS))
    rollback_product_memories_for_batch(
        external_file,
        apply_batch_id=batch['batch_id'],
        actor=actor,
        request=request,
    )
    now = timezone.now()
    summary = copy.deepcopy(external_file.import_summary or {})
    batches = list(summary.get('product_reconciliation_apply_batches') or [])
    for stored in batches:
        if stored.get('batch_id') == batch['batch_id']:
            stored['rolled_back_at'] = now.isoformat()
            stored['rolled_back_by_id'] = getattr(actor, 'pk', None)
    summary['product_reconciliation_apply_batches'] = batches
    external_file.import_summary = summary
    external_file.save(update_fields=['import_summary'])
    ProductReconciliationDecision.objects.filter(
        external_file=external_file,
        apply_batch_id=batch['batch_id'],
    ).update(
        decision_status='READY', applied_by=None, applied_at=None, apply_batch_id=''
    )
    create_audit_event(
        event_type='PRODUCT_RECONCILIATION_ROLLED_BACK',
        message=f'{len(batch["changes"])} Product change(s) rolled back.',
        actor=actor,
        client=external_file.client,
        external_file=external_file,
        metadata={'batch_id': batch['batch_id']},
        request=request,
    )
    return batch

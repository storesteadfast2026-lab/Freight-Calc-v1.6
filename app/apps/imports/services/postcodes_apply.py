from __future__ import annotations

import copy
import re
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent

from apps.imports.models import ExternalDataFile, ExternalDataReviewItem
from apps.imports.services.audit import create_audit_event
from apps.imports.services.review import sync_postcodes_review_items
from apps.locations.models import Suburb

AU_STATES = {'ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA'}
POSTCODE_RE = re.compile(r'^\d{4}$')
APPROVED_DECISIONS = {'ACCEPT_SOURCE', 'MANUAL_OVERRIDE'}

class PostcodesApplyBlocked(Exception):
    def __init__(self, message, plan=None):
        super().__init__(message)
        self.plan = plan or {}

def _norm(value): return str(value or '').strip()
def _norm_upper(value): return _norm(value).upper()

def _triplet_from_source(source):
    return {'suburb': _norm_upper(source.get('suburb')), 'state': _norm_upper(source.get('state')), 'postcode': _norm(source.get('postcode'))}

def _triplet_from_suburb(row):
    return {'suburb': _norm_upper(row.suburb_name), 'state': _norm_upper(row.state), 'postcode': _norm(row.postcode)}

def _triplet_tuple(data):
    return (_norm_upper(data.get('suburb')), _norm_upper(data.get('state')), _norm(data.get('postcode')))

def _validate_final(final):
    errors = []
    if not final['suburb']: errors.append('Suburb is empty.')
    if final['state'] not in AU_STATES: errors.append(f"State {final['state'] or '-'} is not a supported Australian state.")
    if not POSTCODE_RE.match(final['postcode']): errors.append('Postcode must contain exactly four digits.')
    elif final['postcode'] == '0000': errors.append('Postcode 0000 is not allowed.')
    return errors

def _actor_name(actor):
    if actor is None: return ''
    get_username = getattr(actor, 'get_username', None)
    return _norm(get_username()) if callable(get_username) else _norm(actor)

def _created_record_for_source(external_file, source):
    source_key = _triplet_tuple(source)
    for row in (external_file.import_summary or {}).get('created_rows') or []:
        row_key = (_norm_upper(row.get('suburb') or row.get('suburb_name')), _norm_upper(row.get('state')), _norm(row.get('postcode')))
        if row_key != source_key: continue
        raw_id = row.get('suburb_id') if row.get('suburb_id') is not None else row.get('id')
        if raw_id is None: continue
        result = dict(row); result['suburb_id'] = int(raw_id); return result
    return None

def _get_row(pk, lock=False):
    if not pk: return None
    qs = Suburb.objects.select_for_update() if lock else Suburb.objects
    return qs.filter(pk=pk).first()

def _exact_rows(final, lock=False):
    qs = Suburb.objects.select_for_update() if lock else Suburb.objects
    return list(qs.filter(suburb_name=final['suburb'], state=final['state'], postcode=final['postcode']).order_by('pk'))

def _reference_summary(row):
    refs = []
    if row is None: return refs
    for relation in Suburb._meta.related_objects:
        if getattr(relation, 'many_to_many', False):
            refs.append({'model': relation.related_model._meta.label, 'count': None, 'unsupported': True}); continue
        field = getattr(relation, 'field', None)
        lookup = getattr(field, 'attname', None) if field is not None else None
        if not lookup: continue
        count = relation.related_model._default_manager.filter(**{lookup: row.pk}).count()
        if count: refs.append({'model': relation.related_model._meta.label, 'count': count, 'unsupported': False})
    return refs

def _selected_target_allowed(item, target_id):
    if target_id is None: return True
    allowed = {int(m['id']) for m in ((item.current_data or {}).get('historical_matches') or []) if m.get('id') is not None}
    return int(target_id) in allowed

def _final_for_item(item):
    if item.decision == 'MANUAL_OVERRIDE':
        return {'suburb': _norm_upper(item.corrected_suburb), 'state': _norm_upper(item.corrected_state), 'postcode': _norm(item.corrected_postcode)}
    return _triplet_from_source(item.source_data or {})

def _build_item_plan(external_file, item, lock=False):
    source = _triplet_from_source(item.source_data or {})
    final = _final_for_item(item)
    created_record = _created_record_for_source(external_file, source)
    created_id = created_record.get('suburb_id') if created_record else None
    created_row = _get_row(created_id, lock=lock)
    target_id = item.selected_historical_suburb_id
    target_row = _get_row(target_id, lock=lock)
    plan = {
        'review_item_id': item.pk, 'row_key': item.row_key, 'decision': item.decision,
        'source': source, 'final': final, 'target_id': target_id,
        'target_before': _triplet_from_suburb(target_row) if target_row else None,
        'created_id': created_id, 'created_before': _triplet_from_suburb(created_row) if created_row else None,
        'operation': 'NO_CHANGE', 'display_action': 'NO CHANGE', 'blockers': [], 'reference_summary': [],
    }
    if item.decision not in APPROVED_DECISIONS:
        plan['display_action'] = 'SKIP'; return plan
    if item.decision == 'MANUAL_OVERRIDE' and not _norm(item.notes): plan['blockers'].append('Manual override requires Notes.')
    plan['blockers'].extend(_validate_final(final))
    if target_id is not None:
        if not _selected_target_allowed(item, target_id): plan['blockers'].append('Selected Current DB row is no longer one of the review candidates.')
        if target_row is None: plan['blockers'].append(f'Selected Current DB row #{target_id} no longer exists.')
    if created_row is not None and created_id == target_id: plan['blockers'].append('The Current DB target cannot be the row created by this same source file.')
    exact_rows = _exact_rows(final, lock=lock)
    allowed_exact_ids = {pk for pk in (target_id, created_id) if pk is not None}
    unrelated = [row.pk for row in exact_rows if row.pk not in allowed_exact_ids]
    if unrelated: plan['blockers'].append('Final postcode row already exists outside this review/source context: ' + ', '.join(str(pk) for pk in unrelated))
    if plan['blockers']: plan['display_action'] = 'BLOCKED'; return plan
    if target_row is not None:
        target_triplet = _triplet_from_suburb(target_row)
        created_refs = _reference_summary(created_row) if created_row else []
        plan['reference_summary'] = created_refs
        if created_row is not None and created_id != target_id:
            unsupported = [r for r in created_refs if r.get('unsupported')]
            used = [r for r in created_refs if not r.get('unsupported') and r.get('count')]
            if unsupported: plan['blockers'].append('The source-created row has an unsupported relationship and cannot be merged safely.')
            if used: plan['blockers'].append('The source-created row is already referenced and cannot be deleted safely: ' + ', '.join(f"{r['model']}={r['count']}" for r in used))
            if plan['blockers']: plan['display_action'] = 'BLOCKED'; return plan
        if target_triplet == final:
            if created_row is not None and created_id != target_id:
                plan['operation'] = 'DELETE_CREATED_DUPLICATE_ONLY'; plan['display_action'] = 'CLEAN DUPLICATE'
            else:
                plan['display_action'] = 'ALREADY APPLIED'
            return plan
        plan['operation'] = 'REPLACE_TARGET'; plan['display_action'] = 'REPLACE'; return plan
    if created_row is not None:
        if _triplet_from_suburb(created_row) == final:
            plan['display_action'] = 'ALREADY ADDED'; return plan
        plan['operation'] = 'UPDATE_CREATED'; plan['display_action'] = 'UPDATE ADDED'; return plan
    if exact_rows:
        plan['display_action'] = 'ALREADY EXISTS'; return plan
    plan['operation'] = 'CREATE'; plan['display_action'] = 'ADD'; return plan

def build_postcodes_apply_plan(external_file_id, lock=False):
    file_qs = ExternalDataFile.objects.select_for_update() if lock else ExternalDataFile.objects
    external_file = file_qs.get(pk=external_file_id)
    plan = {'external_file_id': external_file.pk, 'filename': external_file.original_filename, 'file_type': external_file.file_type, 'status': external_file.status, 'items': [], 'approved_count': 0, 'change_count': 0, 'no_change_count': 0, 'skipped_count': 0, 'blockers': []}
    if external_file.file_type != 'SUBURBS': plan['blockers'].append('Apply approved changes is only enabled for SUBURBS.'); return plan
    if external_file.status != 'ACTIVE': plan['blockers'].append(f'External data file must be ACTIVE before Review changes can be applied. Current status: {external_file.status}.'); return plan
    item_qs = ExternalDataReviewItem.objects.filter(external_file=external_file, is_current=True).order_by('pk')
    if lock: item_qs = item_qs.select_for_update()
    for item in item_qs:
        ip = _build_item_plan(external_file, item, lock=lock); plan['items'].append(ip)
        if item.decision in APPROVED_DECISIONS: plan['approved_count'] += 1
        else: plan['skipped_count'] += 1
        if ip['blockers']:
            plan['blockers'].extend(f"{ip['row_key']}: {b}" for b in ip['blockers'])
        elif ip['operation'] == 'NO_CHANGE' and item.decision in APPROVED_DECISIONS: plan['no_change_count'] += 1
        elif ip['operation'] in {'CREATE','UPDATE_CREATED','REPLACE_TARGET','DELETE_CREATED_DUPLICATE_ONLY'}: plan['change_count'] += 1
    return plan

def _set_row_values(row, values):
    row.suburb_name = values['suburb']; row.state = values['state']; row.postcode = values['postcode']; row.save(update_fields=['suburb_name','state','postcode'])

def _append_batch(external_file, batch):
    summary = copy.deepcopy(external_file.import_summary or {}); batches = list(summary.get('review_apply_batches') or []); batches.append(batch); summary['review_apply_batches'] = batches; external_file.import_summary = summary; external_file.save(update_fields=['import_summary'])

@transaction.atomic
def apply_approved_postcodes(external_file_id, actor=None, request=None):
    plan = build_postcodes_apply_plan(external_file_id, lock=True)
    if plan['blockers']: raise PostcodesApplyBlocked('Approved postcode changes are blocked. Resolve the blockers before applying.', plan=plan)
    if plan['approved_count'] == 0: raise PostcodesApplyBlocked('There are no approved postcode Review decisions to apply.', plan=plan)
    external_file = ExternalDataFile.objects.select_for_update().get(pk=external_file_id)
    if plan['change_count'] == 0 and _latest_open_batch(external_file):
        raise PostcodesApplyBlocked(
            'All approved postcode changes are already applied. No database changes are required.',
            plan=plan,
        )
    now = timezone.now(); batch_id = uuid.uuid4().hex; actor_name = _actor_name(actor); applied_items = []
    item_map = {i.pk:i for i in ExternalDataReviewItem.objects.select_for_update().filter(external_file=external_file,is_current=True)}
    for ip in plan['items']:
        if ip['decision'] not in APPROVED_DECISIONS: continue
        item = item_map[ip['review_item_id']]; op = ip['operation']
        result = {'review_item_id': item.pk, 'batch_id': batch_id, 'operation': op, 'display_action': ip['display_action'], 'actor': actor_name, 'applied_at': now.isoformat(), 'source': ip['source'], 'final': ip['final'], 'target_id': ip['target_id'], 'target_before': ip['target_before'], 'created_id_before': ip['created_id'], 'created_before': ip['created_before']}
        if op == 'CREATE':
            row = Suburb.objects.create(suburb_name=ip['final']['suburb'], state=ip['final']['state'], postcode=ip['final']['postcode']); result['created_id_after'] = row.pk
        elif op == 'UPDATE_CREATED':
            row = Suburb.objects.select_for_update().get(pk=ip['created_id']); _set_row_values(row, ip['final']); result['created_id_after'] = row.pk
        elif op == 'REPLACE_TARGET':
            target = Suburb.objects.select_for_update().get(pk=ip['target_id'])
            if ip['created_id'] is not None and ip['created_id'] != target.pk:
                created = Suburb.objects.select_for_update().filter(pk=ip['created_id']).first()
                if created is not None: created.delete(); result['deleted_created_id'] = ip['created_id']
            _set_row_values(target, ip['final']); result['target_id_after'] = target.pk
        elif op == 'DELETE_CREATED_DUPLICATE_ONLY':
            created = Suburb.objects.select_for_update().get(pk=ip['created_id']); created.delete(); result['deleted_created_id'] = ip['created_id']; result['target_id_after'] = ip['target_id']
        elif op != 'NO_CHANGE':
            raise PostcodesApplyBlocked(f'Unsupported apply operation: {op}', plan=plan)
        item.applied_at = now; item.applied_result = result
        if actor is not None and getattr(actor,'pk',None): item.reviewed_by = actor
        item.save(update_fields=['applied_at','applied_result','reviewed_by','updated_at']); applied_items.append(result)
    batch = {'batch_id':batch_id,'applied_at':now.isoformat(),'actor':actor_name,'approved_count':plan['approved_count'],'change_count':plan['change_count'],'no_change_count':plan['no_change_count'],'items':applied_items,'rolled_back_at':None,'rolled_back_by':''}
    _append_batch(external_file,batch)
    ensure_postcodes_apply_audit_event(
        external_file.pk,
        actor=actor,
        request=request,
        batch_id=batch_id,
    )
    sync_postcodes_review_items(external_file)
    return {'batch_id':batch_id,'approved_count':plan['approved_count'],'change_count':plan['change_count'],'no_change_count':plan['no_change_count']}

def _latest_open_batch(external_file):
    for batch in reversed(list((external_file.import_summary or {}).get('review_apply_batches') or [])):
        if not batch.get('rolled_back_at'): return batch
    return None

def build_postcodes_rollback_plan(external_file_id, lock=False):
    file_qs = ExternalDataFile.objects.select_for_update() if lock else ExternalDataFile.objects
    external_file = file_qs.get(pk=external_file_id); batch = _latest_open_batch(external_file)
    plan = {'external_file_id':external_file.pk,'batch':batch,'items':[],'blockers':[]}
    if not batch: plan['blockers'].append('There is no applied Review batch available to rollback.'); return plan
    for item in reversed(batch.get('items') or []):
        op=item.get('operation'); row_plan={'operation':op,'review_item_id':item.get('review_item_id'),'source':item.get('source'),'final':item.get('final'),'blockers':[]}
        if op == 'CREATE':
            rid=item.get('created_id_after'); row=_get_row(rid,lock=lock)
            if row is None: row_plan['blockers'].append(f'Created row #{rid} no longer exists.')
            elif [r for r in _reference_summary(row) if r.get('unsupported') or r.get('count')]: row_plan['blockers'].append(f'Created row #{rid} is now referenced and cannot be removed safely.')
        elif op == 'UPDATE_CREATED':
            rid=item.get('created_id_after') or item.get('created_id_before'); row=_get_row(rid,lock=lock)
            if row is None: row_plan['blockers'].append(f'Updated source-created row #{rid} no longer exists.')
            elif _triplet_from_suburb(row) != item.get('final'): row_plan['blockers'].append(f'Updated source-created row #{rid} has changed since Apply.')
        elif op in {'REPLACE_TARGET','DELETE_CREATED_DUPLICATE_ONLY'}:
            tid=item.get('target_id_after') or item.get('target_id'); target=_get_row(tid,lock=lock)
            if target is None: row_plan['blockers'].append(f'Replaced Current DB row #{tid} no longer exists.')
            elif _triplet_from_suburb(target) != item.get('final'): row_plan['blockers'].append(f'Replaced Current DB row #{tid} has changed since Apply.')
            did=item.get('deleted_created_id')
            if did and _get_row(did,lock=lock) is not None: row_plan['blockers'].append(f'Source-created row #{did} already exists; rollback would conflict.')
        elif op != 'NO_CHANGE': row_plan['blockers'].append(f'Unsupported rollback operation: {op}')
        plan['items'].append(row_plan); plan['blockers'].extend(row_plan['blockers'])
    return plan

@transaction.atomic
def rollback_latest_postcodes_apply(external_file_id, actor=None, request=None):
    plan=build_postcodes_rollback_plan(external_file_id,lock=True)
    if plan['blockers']: raise PostcodesApplyBlocked('The latest postcode Apply batch cannot be rolled back safely.',plan=plan)
    external_file=ExternalDataFile.objects.select_for_update().get(pk=external_file_id); batch=_latest_open_batch(external_file); actor_name=_actor_name(actor); now=timezone.now()
    for item in reversed(batch.get('items') or []):
        op=item.get('operation')
        if op == 'CREATE': Suburb.objects.select_for_update().get(pk=item['created_id_after']).delete()
        elif op == 'UPDATE_CREATED': _set_row_values(Suburb.objects.select_for_update().get(pk=item.get('created_id_after') or item.get('created_id_before')), item['created_before'])
        elif op == 'REPLACE_TARGET':
            target=Suburb.objects.select_for_update().get(pk=item.get('target_id_after') or item.get('target_id')); _set_row_values(target,item['target_before'])
            did=item.get('deleted_created_id')
            if did and item.get('created_before'): Suburb.objects.create(pk=did,suburb_name=item['created_before']['suburb'],state=item['created_before']['state'],postcode=item['created_before']['postcode'])
        elif op == 'DELETE_CREATED_DUPLICATE_ONLY':
            did=item.get('deleted_created_id')
            if did and item.get('created_before'): Suburb.objects.create(pk=did,suburb_name=item['created_before']['suburb'],state=item['created_before']['state'],postcode=item['created_before']['postcode'])
    summary=copy.deepcopy(external_file.import_summary or {}); batches=list(summary.get('review_apply_batches') or [])
    for stored in reversed(batches):
        if stored.get('batch_id') == batch.get('batch_id'): stored['rolled_back_at']=now.isoformat(); stored['rolled_back_by']=actor_name; break
    summary['review_apply_batches']=batches; external_file.import_summary=summary; external_file.save(update_fields=['import_summary'])
    ids=[i.get('review_item_id') for i in batch.get('items') or [] if i.get('review_item_id')]
    for review_item in ExternalDataReviewItem.objects.select_for_update().filter(pk__in=ids):
        result=copy.deepcopy(review_item.applied_result or {})
        if result.get('batch_id') == batch.get('batch_id'): result['rolled_back_at']=now.isoformat(); result['rolled_back_by']=actor_name; review_item.applied_result=result; review_item.save(update_fields=['applied_result','updated_at'])
    create_audit_event(
        event_type='POSTCODES_REVIEW_ROLLED_BACK',
        message=(
            f'Postcodes Review Apply batch {batch.get("batch_id")} rolled back '
            f'for {external_file.client.code}.'
        ),
        actor=actor,
        client=external_file.client,
        external_file=external_file,
        severity='WARNING',
        metadata={
            'source_file': external_file.original_filename,
            'sha256': external_file.sha256,
            'apply_batch_id': batch.get('batch_id'),
            'applied_at': batch.get('applied_at'),
            'rolled_back_at': now.isoformat(),
            'applied_change_count': batch.get('change_count', 0),
            'approved_count': batch.get('approved_count', 0),
            'database_updated': True,
        },
        request=request,
    )
    sync_postcodes_review_items(external_file)
    return {'batch_id':batch.get('batch_id'),'rolled_back_at':now.isoformat()}


def _apply_audit_metadata(external_file, batch):
    return {
        'source_file': external_file.original_filename,
        'file_type': external_file.file_type,
        'source_method': external_file.source_method,
        'sha256': external_file.sha256,
        'batch_id': batch.get('batch_id'),
        'applied_at': batch.get('applied_at'),
        'original_actor': batch.get('actor', ''),
        'approved_count': batch.get('approved_count', 0),
        'change_count': batch.get('change_count', 0),
        'no_change_count': batch.get('no_change_count', 0),
        'database_updated': bool(batch.get('change_count', 0)),
        'items': list(batch.get('items') or []),
    }


def _batch_actor(batch):
    username = _norm(batch.get('actor'))
    if not username:
        return None
    return get_user_model().objects.filter(username=username).first()


def _find_apply_audit_event(external_file, batch_id):
    if not batch_id:
        return None
    return (
        AuditEvent.objects.filter(
            external_file=external_file,
            event_type='POSTCODES_REVIEW_APPLIED',
            metadata__batch_id=batch_id,
        )
        .order_by('pk')
        .first()
    )


def ensure_postcodes_apply_audit_event(
    external_file_id,
    actor=None,
    request=None,
    batch_id=None,
):
    """
    Ensure one AuditEvent exists for a successful Postcodes Apply batch.

    This is idempotent and is also used to backfill the Apply batch that was
    created before Postcodes Review was connected to Audit Events.
    """
    external_file = ExternalDataFile.objects.get(pk=external_file_id)

    if batch_id:
        batch = next(
            (
                stored
                for stored in reversed(
                    list(
                        (external_file.import_summary or {}).get(
                            'review_apply_batches'
                        )
                        or []
                    )
                )
                if stored.get('batch_id') == batch_id
                and not stored.get('rolled_back_at')
            ),
            None,
        )
    else:
        batch = _latest_open_batch(external_file)

    if not batch:
        raise PostcodesApplyBlocked(
            'There is no successful active Postcodes Review Apply batch to audit.'
        )

    existing = _find_apply_audit_event(external_file, batch.get('batch_id'))
    if existing is not None:
        return {
            'created': False,
            'audit_event_id': existing.pk,
            'batch_id': batch.get('batch_id'),
        }

    audit_actor = actor or _batch_actor(batch)
    event = create_audit_event(
        event_type='POSTCODES_REVIEW_APPLIED',
        message=(
            f'Postcodes Review applied for {external_file.client.code}: '
            f'{batch.get("change_count", 0)} database change(s), '
            f'{batch.get("no_change_count", 0)} already applied/no-change.'
        ),
        actor=audit_actor,
        client=external_file.client,
        external_file=external_file,
        metadata=_apply_audit_metadata(external_file, batch),
        request=request,
        request_id=batch.get('batch_id') or None,
    )
    return {
        'created': True,
        'audit_event_id': event.pk,
        'batch_id': batch.get('batch_id'),
    }


def postcodes_review_completion(external_file_id):
    external_file = ExternalDataFile.objects.get(pk=external_file_id)
    plan = build_postcodes_apply_plan(external_file.pk)
    batch = _latest_open_batch(external_file)
    audit_event = (
        _find_apply_audit_event(external_file, batch.get('batch_id'))
        if batch
        else None
    )

    completed = bool(
        batch
        and audit_event
        and plan['approved_count'] > 0
        and plan['change_count'] == 0
        and plan['skipped_count'] == 0
        and not plan['blockers']
    )

    return {
        'completed': completed,
        'batch_id': batch.get('batch_id') if batch else '',
        'applied_at': batch.get('applied_at') if batch else '',
        'actor': batch.get('actor') if batch else '',
        'approved_count': plan['approved_count'],
        'change_count': plan['change_count'],
        'no_change_count': plan['no_change_count'],
        'skipped_count': plan['skipped_count'],
        'blockers': list(plan['blockers']),
        'audit_event_id': audit_event.pk if audit_event else None,
    }

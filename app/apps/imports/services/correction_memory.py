from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.imports.models import ExternalDataCorrectionMemory
from apps.imports.services.audit import create_audit_event


def canonical_fingerprint(value: Any) -> str:
    """Return a stable fingerprint for JSON-compatible external-source data."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        default=str,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CorrectionMemoryMatch:
    state: str
    memory: ExternalDataCorrectionMemory | None = None

    @property
    def can_reuse(self) -> bool:
        return self.state == 'EXACT' and self.memory is not None


def find_correction_memory(
    *,
    workflow_key: str,
    client,
    record_key: str,
    source_data: dict[str, Any],
) -> CorrectionMemoryMatch:
    source_fingerprint = canonical_fingerprint(source_data)
    exact = (
        ExternalDataCorrectionMemory.objects.filter(
            workflow_key=workflow_key,
            client=client,
            source_fingerprint=source_fingerprint,
            is_active=True,
        )
        .select_related('approved_by', 'origin_external_file')
        .first()
    )
    if exact is not None:
        return CorrectionMemoryMatch('EXACT', exact)

    if record_key:
        changed = (
            ExternalDataCorrectionMemory.objects.filter(
                workflow_key=workflow_key,
                client=client,
                record_key=record_key,
                is_active=True,
            )
            .select_related('approved_by', 'origin_external_file')
            .order_by('-approved_at')
            .first()
        )
        if changed is not None:
            return CorrectionMemoryMatch('SOURCE_CHANGED', changed)
    return CorrectionMemoryMatch('NONE')


@transaction.atomic
def remember_correction(
    *,
    workflow_key: str,
    client,
    record_key: str,
    source_data: dict[str, Any],
    approved_data: dict[str, Any],
    approval_note: str,
    origin_external_file,
    actor=None,
    request=None,
    create_audit=True,
) -> ExternalDataCorrectionMemory:
    source_fingerprint = canonical_fingerprint(source_data)
    proposal_fingerprint = canonical_fingerprint(approved_data)
    memory, created = ExternalDataCorrectionMemory.objects.select_for_update().get_or_create(
        workflow_key=workflow_key,
        client=client,
        source_fingerprint=source_fingerprint,
        defaults={
            'record_key': record_key,
            'proposal_fingerprint': proposal_fingerprint,
            'source_data': source_data,
            'approved_data': approved_data,
            'approval_note': (approval_note or '').strip(),
            'origin_external_file': origin_external_file,
            'approved_by': actor if getattr(actor, 'is_authenticated', False) else None,
            'last_used_at': timezone.now(),
            'use_count': 1,
        },
    )
    if not created:
        memory.record_key = record_key
        memory.proposal_fingerprint = proposal_fingerprint
        memory.source_data = source_data
        memory.approved_data = approved_data
        memory.approval_note = (approval_note or '').strip()
        memory.origin_external_file = origin_external_file
        memory.approved_by = actor if getattr(actor, 'is_authenticated', False) else None
        memory.approved_at = timezone.now()
        memory.last_used_at = timezone.now()
        memory.use_count = F('use_count') + 1
        memory.is_active = True
        memory.save(update_fields=[
            'record_key', 'proposal_fingerprint', 'source_data', 'approved_data',
            'approval_note', 'origin_external_file', 'approved_by', 'approved_at',
            'last_used_at', 'use_count', 'is_active',
        ])
        memory.refresh_from_db()

    if create_audit:
        create_audit_event(
            event_type='EXTERNAL_CORRECTION_MEMORY_RECORDED',
            message=(
                f'Correction memory {"created" if created else "reused"} for '
                f'{workflow_key} record {record_key or "without key"}.'
            ),
            actor=actor,
            client=client,
            external_file=origin_external_file,
            metadata={
                'correction_memory_id': memory.pk,
                'workflow_key': workflow_key,
                'record_key': record_key,
                'source_fingerprint': source_fingerprint,
                'proposal_fingerprint': proposal_fingerprint,
                'memory_created': created,
                'operational_tables_updated': False,
            },
            request=request,
        )
    return memory


def mark_correction_memories_used(memory_ids):
    """Record that one or more active memories produced a reconciliation draft."""
    ids = list(dict.fromkeys(memory_id for memory_id in memory_ids if memory_id))
    if not ids:
        return 0
    return ExternalDataCorrectionMemory.objects.filter(
        pk__in=ids,
        is_active=True,
    ).update(
        last_used_at=timezone.now(),
        use_count=F('use_count') + 1,
    )

from __future__ import annotations

from typing import Any
from uuid import uuid4

from apps.audit.models import AuditEvent


def get_request_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip() or None
    return request.META.get('REMOTE_ADDR') or None


def create_audit_event(
    *,
    event_type: str,
    message: str,
    actor=None,
    client=None,
    external_file=None,
    severity: str = 'INFO',
    metadata: dict[str, Any] | None = None,
    request=None,
    request_id: str | None = None,
) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        client=client,
        external_file=external_file,
        event_type=event_type,
        severity=severity,
        message=message,
        metadata=metadata or {},
        ip_address=get_request_ip(request),
        request_id=request_id or uuid4().hex,
    )

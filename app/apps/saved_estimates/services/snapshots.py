from decimal import Decimal, InvalidOperation
import re
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.authentication_gateway.services import resolve_authorized_client

from ..models import SavedEstimate
from .calculation_bridge import (
    SnapshotValidationError,
    normalise_displayed_results,
    recalculate_snapshot,
)


def _pending_reference():
    """Return a unique temporary value that fits reference.max_length."""
    return f'PENDING-{uuid4().hex[:24]}'


def _client_reference_code(client_code):
    """Return a short URL/file-safe client token for quote references."""
    token = re.sub(r'[^A-Z0-9]+', '-', str(client_code or '').upper()).strip('-')
    return (token or 'CLIENT')[:20]


def _final_reference(estimate):
    """Build a globally unique, human-readable freight quotation reference."""
    local_date = timezone.localtime(estimate.created_at).strftime('%Y%m%d')
    client_code = _client_reference_code(estimate.client.code)
    # SavedEstimate.pk comes from PostgreSQL's global sequence, so it is unique
    # across all clients. Eight digits is a minimum width, not a hard limit.
    return f'FQ-{client_code}-{local_date}-{estimate.pk:08d}'


@transaction.atomic
def create_verified_estimate(user, calculation_payload, displayed_results):
    client = resolve_authorized_client(
        user,
        (calculation_payload or {}).get('client_code'),
    )
    input_snapshot, verified_results = recalculate_snapshot(
        calculation_payload,
        client,
    )
    browser_results = normalise_displayed_results(displayed_results)

    if browser_results != verified_results:
        raise SnapshotValidationError(
            'Rates or calculation data changed. Calculate freight again before saving.'
        )
    if not verified_results:
        raise SnapshotValidationError('There are no freight results to save.')

    first_details = verified_results[0].get('details') or {}
    estimate = SavedEstimate.objects.create(
        reference=_pending_reference(),
        client=client,
        created_by=user,
        created_by_label=user.email or user.get_username(),
        schema_version=1,
        input_snapshot=input_snapshot,
        result_snapshot=verified_results,
        destination_label=_destination_label(input_snapshot),
        total_weight_kg=_optional_decimal(first_details.get('actual_weight')),
        total_cubic_m3=_optional_decimal(first_details.get('cubic_total')),
        best_estimate_ex_gst=_optional_decimal(
            verified_results[0].get('estimate_ex_gst')
        ),
    )
    estimate.reference = _final_reference(estimate)
    estimate.save(update_fields=['reference'])
    return estimate


def _destination_label(snapshot):
    suburb = snapshot.get('suburb', '')
    state = snapshot.get('state', '')
    postcode = snapshot.get('postcode', '') or ''
    return ', '.join(part for part in [suburb, f'{state} {postcode}'.strip()] if part)


def _optional_decimal(value):
    if value in [None, '']:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None

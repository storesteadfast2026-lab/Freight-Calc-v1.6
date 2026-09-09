from __future__ import annotations

from django.db import transaction

from apps.imports.models import ExternalDataFile, ExternalDataReviewItem
from apps.locations.models import Suburb


POSTCODES_ENTITY_TYPE = 'SUBURB'


def build_postcodes_review_row_key(row: dict) -> str:
    suburb = str(row.get('suburb') or '').strip().upper()
    state = str(row.get('state') or '').strip().upper()
    postcode = str(row.get('postcode') or '').strip().upper()
    return f'SUBURBS|{state}|{postcode}|{suburb}'


def _created_row_for_source(external_file: ExternalDataFile, row: dict) -> dict:
    suburb = str(row.get('suburb') or '').strip().upper()
    state = str(row.get('state') or '').strip().upper()
    postcode = str(row.get('postcode') or '').strip().upper()
    for created in (external_file.import_summary or {}).get('created_rows') or []:
        if (
            str(created.get('suburb') or '').strip().upper() == suburb
            and str(created.get('state') or '').strip().upper() == state
            and str(created.get('postcode') or '').strip().upper() == postcode
        ):
            return created
    return {}


def _created_suburb_ids(external_file: ExternalDataFile) -> set[int]:
    """Return IDs created by this ExternalDataFile activation.

    Current Postcodes import summaries store the identifier as `suburb_id`.
    `id` remains supported for compatibility with older/test summaries.
    """
    ids: set[int] = set()
    for created in (external_file.import_summary or {}).get('created_rows') or []:
        raw_id = created.get('suburb_id')
        if raw_id is None:
            raw_id = created.get('id')
        try:
            if raw_id is not None:
                ids.add(int(raw_id))
        except (TypeError, ValueError):
            continue
    return ids

def _historical_matches(external_file: ExternalDataFile, source_row: dict) -> list[dict]:
    """Return only useful historical comparisons.

    Relevant comparisons are deliberately narrow:
    - exact historical triplet;
    - same suburb/state with another postcode;
    - validator-provided possible alias in the same state.

    Generic rows that merely share state/postcode are not returned here because
    they create noise and are not useful correction candidates.
    """
    suburb = str(source_row.get('suburb') or '').strip().upper()
    state = str(source_row.get('state') or '').strip().upper()
    postcode = str(source_row.get('postcode') or '').strip().upper()
    alias = str(source_row.get('possible_alias') or '').strip().upper()

    base = Suburb.objects.exclude(pk__in=_created_suburb_ids(external_file))
    candidates: dict[int, dict] = {}

    def add_rows(queryset, match_type: str):
        for row in queryset.order_by('suburb_name', 'postcode', 'pk')[:20]:
            if row.pk not in candidates:
                candidates[row.pk] = {
                    'id': row.pk,
                    'suburb': row.suburb_name,
                    'state': row.state,
                    'postcode': row.postcode,
                    'match_type': match_type,
                }

    add_rows(
        base.filter(
            suburb_name__iexact=suburb,
            state__iexact=state,
            postcode__iexact=postcode,
        ),
        'EXACT_TRIPLET',
    )
    add_rows(
        base.filter(suburb_name__iexact=suburb, state__iexact=state),
        'SAME_SUBURB_STATE',
    )
    if alias:
        add_rows(
            base.filter(suburb_name__iexact=alias, state__iexact=state),
            'VALIDATOR_ALIAS',
        )

    return list(candidates.values())

def _same_state_postcode_other_count(
    external_file: ExternalDataFile,
    source_row: dict,
    direct_matches: list[dict],
) -> int:
    """Count other historical suburbs using the same state/postcode.

    This is informational only. The names are intentionally not returned to the
    Admin table because they are not correction candidates.
    """
    state = str(source_row.get('state') or '').strip().upper()
    postcode = str(source_row.get('postcode') or '').strip().upper()
    direct_ids = {
        int(match['id'])
        for match in direct_matches
        if match.get('id') is not None
    }

    return (
        Suburb.objects
        .exclude(pk__in=_created_suburb_ids(external_file))
        .exclude(pk__in=direct_ids)
        .filter(state__iexact=state, postcode__iexact=postcode)
        .count()
    )


def classify_postcodes_source_action(
    source_row: dict,
    current_db_matches: list[dict],
) -> dict:
    """Classify the source-authoritative proposal without changing operational data.

    The source row wins by policy. This function only describes what would be
    required relative to the current DB:
    - exact source row already exists -> UNCHANGED;
    - no direct current DB candidate -> ADD;
    - one or more direct current DB candidates differ -> REPLACE.

    REPLACE remains review-only until the stable business key for operational
    replacement is confirmed and a protected apply step is implemented.
    """
    source_key = (
        str(source_row.get('suburb') or '').strip().upper(),
        str(source_row.get('state') or '').strip().upper(),
        str(source_row.get('postcode') or '').strip(),
    )

    exact_matches = []
    for match in current_db_matches:
        match_key = (
            str(match.get('suburb') or '').strip().upper(),
            str(match.get('state') or '').strip().upper(),
            str(match.get('postcode') or '').strip(),
        )
        if match_key == source_key:
            exact_matches.append(match)

    if exact_matches:
        return {
            'action': 'UNCHANGED',
            'risk': 'OK',
            'reason': 'Exact source row already exists in Current DB.',
        }

    if not current_db_matches:
        return {
            'action': 'ADD',
            'risk': 'OK',
            'reason': 'No direct Current DB candidate was found.',
        }

    if len(current_db_matches) == 1:
        return {
            'action': 'REPLACE',
            'risk': 'REVIEW',
            'reason': 'One Current DB candidate differs from the authoritative source.',
        }

    return {
        'action': 'REPLACE',
        'risk': 'REVIEW',
        'reason': (
            f'{len(current_db_matches)} Current DB candidates differ from the authoritative source.'
        ),
    }


def _created_row_is_live_source(created_row, source_row):
    if not created_row:
        return False
    raw_id = created_row.get('suburb_id')
    if raw_id is None:
        raw_id = created_row.get('id')
    if raw_id is None:
        return False
    return Suburb.objects.filter(
        pk=int(raw_id),
        suburb_name=str(source_row.get('suburb') or '').strip().upper(),
        state=str(source_row.get('state') or '').strip().upper(),
        postcode=str(source_row.get('postcode') or '').strip(),
    ).exists()


@transaction.atomic
def sync_postcodes_review_items(external_file: ExternalDataFile) -> dict:
    """Synchronise review metadata only; operational postcode data is untouched."""
    if external_file.pk is None:
        raise ValueError('ExternalDataFile must be saved before review items can be synchronised.')

    locked_file = ExternalDataFile.objects.select_for_update().get(pk=external_file.pk)
    if locked_file.file_type != 'SUBURBS':
        return {
            'external_file_id': locked_file.pk,
            'file_type': locked_file.file_type,
            'created': 0,
            'updated': 0,
            'current': 0,
            'ignored': True,
        }

    summary = locked_file.validation_summary or {}
    preview_rows = summary.get('new_rows_preview') or summary.get('would_add_preview') or []

    ExternalDataReviewItem.objects.filter(
        external_file=locked_file,
        entity_type=POSTCODES_ENTITY_TYPE,
        is_current=True,
    ).update(is_current=False)

    created_count = 0
    updated_count = 0

    for source_row in preview_rows:
        row_key = build_postcodes_review_row_key(source_row)
        historical_matches = _historical_matches(locked_file, source_row)
        created_row = _created_row_for_source(locked_file, source_row)
        source_action = classify_postcodes_source_action(
            source_row,
            historical_matches,
        )
        if not historical_matches and _created_row_is_live_source(created_row, source_row):
            source_action = {
                'action': 'ALREADY_ADDED',
                'risk': 'OK',
                'reason': 'Source row is already present from this file activation.',
            }
        same_state_postcode_other_count = _same_state_postcode_other_count(
            locked_file,
            source_row,
            historical_matches,
        )
        diagnostic_data = {
            'possible_alias': source_row.get('possible_alias') or '',
            'existing_same_suburb_state_postcodes': source_row.get('existing_same_suburb_state_postcodes') or [],
            'names_at_same_state_postcode': source_row.get('names_at_same_state_postcode') or [],
            'historical_matches': historical_matches,
        }
        current_data = {
            'created_row': created_row,
            'historical_matches': historical_matches,
            'same_state_postcode_other_count': same_state_postcode_other_count,
            'source_action': source_action['action'],
            'source_action_risk': source_action['risk'],
            'source_action_reason': source_action['reason'],
        }
        defaults = {
            'entity_type': POSTCODES_ENTITY_TYPE,
            'source_data': source_row,
            'current_data': current_data,
            'diagnostic_data': diagnostic_data,
            'proposed_action': str(source_row.get('action') or 'ADD'),
            'decision': 'PENDING',
            'corrected_suburb': str(source_row.get('suburb') or '').strip().upper(),
            'corrected_state': str(source_row.get('state') or '').strip().upper(),
            'corrected_postcode': str(source_row.get('postcode') or '').strip(),
            'is_current': True,
        }
        review_item, created = ExternalDataReviewItem.objects.get_or_create(
            external_file=locked_file,
            row_key=row_key,
            defaults=defaults,
        )
        if created:
            created_count += 1
            continue

        review_item.entity_type = POSTCODES_ENTITY_TYPE
        review_item.source_data = source_row
        review_item.current_data = current_data
        review_item.diagnostic_data = diagnostic_data
        review_item.proposed_action = str(source_row.get('action') or 'ADD')
        review_item.is_current = True
        if not review_item.corrected_suburb:
            review_item.corrected_suburb = defaults['corrected_suburb']
        if not review_item.corrected_state:
            review_item.corrected_state = defaults['corrected_state']
        if not review_item.corrected_postcode:
            review_item.corrected_postcode = defaults['corrected_postcode']
        review_item.save(update_fields=[
            'entity_type', 'source_data', 'current_data', 'diagnostic_data',
            'proposed_action', 'corrected_suburb', 'corrected_state',
            'corrected_postcode', 'is_current', 'updated_at',
        ])
        updated_count += 1

    return {
        'external_file_id': locked_file.pk,
        'file_type': locked_file.file_type,
        'created': created_count,
        'updated': updated_count,
        'current': len(preview_rows),
        'ignored': False,
    }

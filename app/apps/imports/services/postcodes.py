from __future__ import annotations

import csv
import hashlib
import io
from difflib import SequenceMatcher
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.imports.models import ExternalDataFile
from apps.imports.services.audit import create_audit_event
from apps.locations.models import Suburb
from apps.rates.models import FreightZone


AUSTRALIAN_STATES = {'ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA'}
REQUIRED_COLUMNS = ('index', 'suburb', 'state', 'postcode')
POSTCODES_POLICY_VERSION = 3
POSTCODES_ACTIVATION_POLICY = 'ADD_ONLY_PRESERVE_EXISTING'
ALIAS_SIMILARITY_THRESHOLD = 0.90


class PostcodesImportError(Exception):
    """Raised when a postcodes source cannot be snapshotted, validated, activated or rolled back."""


def uploaded_data_root() -> Path:
    configured = getattr(settings, 'FTP_UPLOADED_DATA_DIR', '')
    if configured:
        return Path(configured).resolve()
    return (Path(settings.BASE_DIR) / 'uploaded_data').resolve()


def resolve_uploaded_postcodes_file(filename: str) -> Path:
    safe_name = Path(str(filename or '')).name
    if not safe_name or safe_name != str(filename or ''):
        raise PostcodesImportError('Postcodes filename must be a simple filename inside uploaded_data.')
    path = (uploaded_data_root() / safe_name).resolve()
    root = uploaded_data_root()
    if path.parent != root:
        raise PostcodesImportError('Postcodes source must be located directly inside uploaded_data.')
    if not path.exists() or not path.is_file():
        raise PostcodesImportError(f'Postcodes source file not found: {path}.')
    if path.suffix.lower() != '.csv':
        raise PostcodesImportError('Postcodes source must be a .csv file.')
    return path


def calculate_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def snapshot_ftp_postcodes_file(*, client, filename='postcodes.csv', actor=None, request=None):
    """Create an immutable snapshot of the FTP drop, or reuse an identical existing snapshot."""
    source_path = resolve_uploaded_postcodes_file(filename)
    content = source_path.read_bytes()
    if not content:
        raise PostcodesImportError('Postcodes source is empty.')

    digest = calculate_sha256(content)
    existing = (
        ExternalDataFile.objects.filter(
            client=client,
            file_type='SUBURBS',
            source_method='FTP_DROP',
            sha256=digest,
        )
        .order_by('-uploaded_at')
        .first()
    )
    if existing is not None:
        create_audit_event(
            event_type='FTP_POSTCODES_SNAPSHOT_SKIPPED',
            message=f'Identical FTP postcodes content already registered for {client.code}.',
            actor=actor,
            client=client,
            external_file=existing,
            metadata={
                'source_path': str(source_path),
                'sha256': digest,
                'existing_file_id': existing.pk,
                'database_updated': False,
            },
            request=request,
        )
        return existing, False

    external_file = ExternalDataFile(
        client=client,
        file_type='SUBURBS',
        source_method='FTP_DROP',
        original_filename=source_path.name,
        stored_path='',
        file_size_bytes=len(content),
        mime_type='text/csv',
        sha256=digest,
        notes=f'Snapshot created from FTP uploaded_data/{source_path.name}.',
        uploaded_by=actor if getattr(actor, 'is_authenticated', False) else None,
        status='UPLOADED',
    )
    external_file.uploaded_file.save(source_path.name, ContentFile(content), save=False)
    external_file.save()
    external_file.stored_path = external_file.uploaded_file.name
    external_file.save(update_fields=['stored_path'])

    create_audit_event(
        event_type='FTP_POSTCODES_SNAPSHOT_CREATED',
        message=f'FTP postcodes snapshot created for {client.code}.',
        actor=actor,
        client=client,
        external_file=external_file,
        metadata={
            'source_path': str(source_path),
            'source_method': 'FTP_DROP',
            'original_filename': source_path.name,
            'stored_filename': external_file.uploaded_file.name,
            'file_size_bytes': len(content),
            'sha256': digest,
            'database_updated': False,
        },
        request=request,
    )
    return external_file, True


def _read_file_bytes(external_file: ExternalDataFile) -> bytes:
    path = external_file.local_path
    if not path:
        raise PostcodesImportError('External postcodes file has no local snapshot path.')
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise PostcodesImportError('The stored postcodes snapshot is not available.')
    return file_path.read_bytes()


def _decode(content: bytes) -> str:
    try:
        return content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise PostcodesImportError('Postcodes CSV must be UTF-8 encoded.') from exc


def parse_postcodes_rows(content: bytes):
    """Parse source rows without changing source values other than normal case/whitespace handling."""
    text = _decode(content)
    reader = csv.DictReader(io.StringIO(text))
    headers = tuple(reader.fieldnames or ())
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise PostcodesImportError(
            'Postcodes CSV is missing required column(s): ' + ', '.join(missing) + '.'
        )

    rows = []
    excluded = []
    seen_source_indexes = set()
    seen_triplets = set()

    for source_row, raw in enumerate(reader, start=2):
        source_index = str(raw.get('index') or '').strip()
        suburb = str(raw.get('suburb') or '').strip().upper()
        state = str(raw.get('state') or '').strip().upper()
        postcode = str(raw.get('postcode') or '').strip()

        blank_fields = [
            name
            for name, value in (
                ('index', source_index),
                ('suburb', suburb),
                ('state', state),
                ('postcode', postcode),
            )
            if not value
        ]
        if blank_fields:
            raise PostcodesImportError(
                f'Postcodes row {source_row} has blank required field(s): {", ".join(blank_fields)}.'
            )

        expected_index = f'{suburb}{state}{postcode}'
        if source_index.upper() != expected_index:
            raise PostcodesImportError(
                f'Postcodes row {source_row} index mismatch: expected {expected_index!r}, '
                f'found {source_index!r}.'
            )

        source_index_key = source_index.upper()
        if source_index_key in seen_source_indexes:
            raise PostcodesImportError(
                f'Postcodes row {source_row} duplicates source index {source_index!r}.'
            )
        seen_source_indexes.add(source_index_key)

        triplet = (suburb, state, postcode)
        if triplet in seen_triplets:
            raise PostcodesImportError(
                f'Postcodes row {source_row} duplicates suburb/state/postcode {triplet!r}.'
            )
        seen_triplets.add(triplet)

        reasons = []
        if state not in AUSTRALIAN_STATES:
            reasons.append(f'non-Australian state {state}')
        if len(postcode) != 4 or not postcode.isdigit() or postcode == '0000':
            reasons.append(f'invalid Australian postcode {postcode}')

        item = {
            'source_row': source_row,
            'source_index': source_index,
            'suburb': suburb,
            'state': state,
            'postcode': postcode,
            'normalized_key': f'{state}{suburb}',
        }
        if reasons:
            item['reason'] = '; '.join(reasons)
            excluded.append(item)
            continue
        rows.append(item)

    if not rows:
        raise PostcodesImportError('Postcodes CSV contains no usable Australian postcode rows.')
    return rows, excluded


def _compact_suburb_name(value: str) -> str:
    return ''.join(character for character in str(value or '').upper() if character.isalnum())


def _best_alias_candidate(target: str, candidates):
    """Return a diagnostic-only possible alias. It never blocks or rewrites a source row."""
    target_name = str(target or '').strip().upper()
    target_compact = _compact_suburb_name(target_name)
    best = None
    for candidate in sorted({str(value or '').strip().upper() for value in candidates if value}):
        if candidate == target_name:
            continue
        candidate_compact = _compact_suburb_name(candidate)
        if target_compact and candidate_compact == target_compact:
            score = 1.0
        else:
            score = SequenceMatcher(None, target_name, candidate).ratio()
        if best is None or score > best[0]:
            best = (score, candidate)
    return best


def _new_row_diagnostics(new_rows, current_set):
    current_by_state_postcode = {}
    current_by_suburb_state = {}
    for suburb, state, postcode in current_set:
        current_by_state_postcode.setdefault((state, postcode), set()).add(suburb)
        current_by_suburb_state.setdefault((suburb, state), set()).add(postcode)

    diagnostics = []
    for suburb, state, postcode in sorted(new_rows):
        same_postcode_names = sorted(current_by_state_postcode.get((state, postcode), set()))
        other_postcodes = sorted(current_by_suburb_state.get((suburb, state), set()))
        alias = _best_alias_candidate(suburb, same_postcode_names)
        likely_alias = alias if alias and alias[0] >= ALIAS_SIMILARITY_THRESHOLD else None
        diagnostics.append({
            'suburb': suburb,
            'state': state,
            'postcode': postcode,
            'status': 'NEW_FROM_FTP_POSTCODES',
            'action': 'ADD',
            'existing_same_suburb_state_postcodes': other_postcodes[:20],
            'existing_names_at_same_state_postcode': same_postcode_names[:20],
            'possible_alias': likely_alias[1] if likely_alias else '',
            'possible_alias_similarity': round(likely_alias[0], 3) if likely_alias else None,
            'diagnostic_only': True,
        })
    return diagnostics


def _existing_origin_label() -> str:
    """Describe existing-master provenance without changing the Suburb operational model."""
    previous_ftp_import = ExternalDataFile.objects.filter(
        file_type='SUBURBS',
        source_method='FTP_DROP',
        last_imported_at__isnull=False,
    ).exists()
    if previous_ftp_import:
        return 'EXISTING_MASTER_WORKBOOK_OR_PRIOR_FTP_POSTCODES'
    return 'LEGACY_WORKBOOK_SUBURBS'


def build_validation_summary(external_file: ExternalDataFile, candidate_rows, excluded_rows) -> dict:
    candidate_set = {
        (row['suburb'], row['state'], row['postcode']) for row in candidate_rows
    }
    current_set = {
        (
            str(suburb or '').strip().upper(),
            str(state or '').strip().upper(),
            str(postcode or '').strip(),
        )
        for suburb, state, postcode in Suburb.objects.values_list(
            'suburb_name', 'state', 'postcode'
        )
    }

    existing_matches = candidate_set & current_set
    new_to_add = sorted(candidate_set - current_set)
    preserve_existing = sorted(current_set - candidate_set)
    new_diagnostics = _new_row_diagnostics(new_to_add, current_set)

    suburb_state_counts = {}
    for suburb, state, postcode in candidate_set:
        key = (suburb, state)
        suburb_state_counts[key] = suburb_state_counts.get(key, 0) + 1
    multi_postcode_groups = sum(1 for count in suburb_state_counts.values() if count > 1)

    warnings = []
    if excluded_rows:
        warnings.append(
            f'{len(excluded_rows)} source row(s) are excluded because they are not valid Australian '
            'suburb/state/postcode candidates. They will not be activated.'
        )
    if preserve_existing:
        warnings.append(
            f'{len(preserve_existing)} existing Django suburb row(s) are not present in this source. '
            'ADD-ONLY policy preserves them unchanged.'
        )
    possible_aliases = [row for row in new_diagnostics if row.get('possible_alias')]
    if possible_aliases:
        warnings.append(
            f'{len(possible_aliases)} new source row(s) resemble existing names. '
            'This is diagnostic only; source rows remain eligible for ADD without automatic renaming.'
        )

    return {
        'source_format': 'FTP_POSTCODES',
        'policy_version': POSTCODES_POLICY_VERSION,
        'activation_policy': POSTCODES_ACTIVATION_POLICY,
        'rows_read': len(candidate_rows) + len(excluded_rows),
        'candidate_rows': len(candidate_rows),
        'excluded_rows_count': len(excluded_rows),
        'existing_confirmed_in_current_source': len(existing_matches),
        'new_rows_to_add': len(new_to_add),
        'existing_not_in_current_source_preserved': len(preserve_existing),
        'existing_master_origin': _existing_origin_label(),
        'new_rows_origin': 'FTP_POSTCODES',
        'existing_action': 'PRESERVE_UNCHANGED',
        'not_in_source_action': 'PRESERVE_EXISTING',
        'new_action': 'ADD',
        'update_existing_allowed': False,
        'delete_existing_allowed': False,
        'rename_existing_allowed': False,
        'freightzone_required_for_add': False,
        'multi_postcode_suburb_state_groups': multi_postcode_groups,
        'new_rows_preview': new_diagnostics[:100],
        'excluded_rows': excluded_rows[:50],
        'preserved_existing_preview': [
            {'suburb': suburb, 'state': state, 'postcode': postcode, 'action': 'PRESERVE_EXISTING'}
            for suburb, state, postcode in preserve_existing[:50]
        ],
        'warnings': warnings,
        'database_updated': False,
        'activation_available': True,
    }


def validate_postcodes_file(external_file: ExternalDataFile, actor=None, request=None) -> dict:
    if external_file.file_type != 'SUBURBS':
        raise PostcodesImportError('External file must have file_type SUBURBS.')

    summary = None
    try:
        content = _read_file_bytes(external_file)
        calculated_hash = calculate_sha256(content)
        candidate_rows, excluded_rows = parse_postcodes_rows(content)
        summary = build_validation_summary(external_file, candidate_rows, excluded_rows)

        external_file.sha256 = calculated_hash
        external_file.file_size_bytes = len(content)
        external_file.status = 'VALIDATED'
        external_file.validation_summary = summary
        external_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
        external_file.validated_at = timezone.now()
        external_file.error_message = ''
        external_file.save(
            update_fields=[
                'sha256', 'file_size_bytes', 'status', 'validation_summary',
                'validated_by', 'validated_at', 'error_message',
            ]
        )
        create_audit_event(
            event_type='FTP_POSTCODES_VALIDATED',
            message=f'FTP postcodes snapshot validated for {external_file.client.code}.',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            metadata=summary,
            request=request,
        )
        return summary
    except Exception as exc:
        external_file.status = 'VALIDATION_FAILED'
        external_file.error_message = str(exc)
        external_file.validation_summary = summary or {
            'source_format': 'FTP_POSTCODES',
            'policy_version': POSTCODES_POLICY_VERSION,
            'activation_policy': POSTCODES_ACTIVATION_POLICY,
            'errors': [str(exc)],
            'database_updated': False,
        }
        external_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
        external_file.validated_at = timezone.now()
        external_file.save(
            update_fields=[
                'status', 'error_message', 'validation_summary', 'validated_by', 'validated_at'
            ]
        )
        create_audit_event(
            event_type='FTP_POSTCODES_VALIDATION_FAILED',
            message=f'FTP postcodes validation failed for {external_file.client.code}.',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            severity='ERROR',
            metadata={'error': str(exc), 'database_updated': False},
            request=request,
        )
        if isinstance(exc, PostcodesImportError):
            raise
        raise PostcodesImportError(str(exc)) from exc


def activate_postcodes_file(external_file: ExternalDataFile, *, actor=None, request=None) -> dict:
    """ADD ONLY. Existing Suburb rows are never updated, renamed or deleted."""
    if external_file.file_type != 'SUBURBS':
        raise PostcodesImportError('Only SUBURBS files can be activated by this operation.')
    if external_file.status != 'VALIDATED':
        raise PostcodesImportError('Validate the postcodes file before activation.')
    summary = external_file.validation_summary or {}
    if (
        summary.get('source_format') != 'FTP_POSTCODES'
        or summary.get('policy_version') != POSTCODES_POLICY_VERSION
        or summary.get('activation_policy') != POSTCODES_ACTIVATION_POLICY
    ):
        raise PostcodesImportError('Re-validate this postcodes snapshot with the current ADD-ONLY policy before activation.')

    content = _read_file_bytes(external_file)
    candidate_rows, excluded_rows = parse_postcodes_rows(content)
    candidate_set = {
        (row['suburb'], row['state'], row['postcode']) for row in candidate_rows
    }
    now = timezone.now()

    try:
        with transaction.atomic():
            locked_file = ExternalDataFile.objects.select_for_update().get(pk=external_file.pk)
            if locked_file.status != 'VALIDATED':
                raise PostcodesImportError('Postcodes snapshot is no longer in VALIDATED status.')

            # Lock existing Suburb rows while computing and applying the additive delta.
            existing_set = {
                (
                    str(suburb or '').strip().upper(),
                    str(state or '').strip().upper(),
                    str(postcode or '').strip(),
                )
                for suburb, state, postcode in Suburb.objects.select_for_update().values_list(
                    'suburb_name', 'state', 'postcode'
                )
            }

            to_create = sorted(candidate_set - existing_set)
            existing_confirmed = candidate_set & existing_set
            preserved_not_in_source = existing_set - candidate_set
            created_rows = []

            for suburb, state, postcode in to_create:
                obj, created = Suburb.objects.get_or_create(
                    suburb_name=suburb,
                    state=state,
                    postcode=postcode,
                    defaults={'normalized_key': f'{state}{suburb}'.upper().strip()},
                )
                if created:
                    created_rows.append({
                        'suburb': suburb,
                        'state': state,
                        'postcode': postcode,
                        'suburb_id': obj.pk,
                        'origin': 'FTP_POSTCODES',
                    })

            previous_active = (
                ExternalDataFile.objects.select_for_update()
                .filter(client=locked_file.client, file_type='SUBURBS', status='ACTIVE')
                .exclude(pk=locked_file.pk)
                .order_by('-activated_at', '-uploaded_at')
                .first()
            )
            if previous_active:
                previous_active.status = 'ARCHIVED'
                previous_active.save(update_fields=['status'])

            import_summary = {
                'policy_version': POSTCODES_POLICY_VERSION,
                'activation_policy': POSTCODES_ACTIVATION_POLICY,
                'source_rows_valid': len(candidate_rows),
                'source_rows_excluded': len(excluded_rows),
                'existing_confirmed_in_current_source': len(existing_confirmed),
                'existing_not_in_current_source_preserved': len(preserved_not_in_source),
                'created_count': len(created_rows),
                'created_rows': created_rows,
                'existing_master_origin_note': (
                    'Rows that existed before this activation were preserved unchanged. '
                    'The verified initial baseline originated from the Excel SUBURBS worksheet; '
                    'later additions are traceable through prior SUBURBS ExternalDataFile import summaries.'
                ),
                'created_rows_origin': 'FTP_POSTCODES',
                'updated_count': 0,
                'deleted_count': 0,
                'renamed_count': 0,
                'previous_active_file_id': previous_active.pk if previous_active else None,
                'source_sha256': locked_file.sha256,
                'source_method': locked_file.source_method,
            }

            locked_file.previous_active_file = previous_active
            locked_file.status = 'ACTIVE'
            locked_file.imported_by = actor if getattr(actor, 'is_authenticated', False) else None
            locked_file.last_imported_at = now
            locked_file.activated_by = actor if getattr(actor, 'is_authenticated', False) else None
            locked_file.activated_at = now
            locked_file.import_summary = import_summary
            locked_file.error_message = ''
            locked_file.save(
                update_fields=[
                    'previous_active_file', 'status', 'imported_by', 'last_imported_at',
                    'activated_by', 'activated_at', 'import_summary', 'error_message',
                ]
            )

            create_audit_event(
                event_type='FTP_POSTCODES_ACTIVATED',
                message=f'FTP postcodes ADD-ONLY activation completed for {locked_file.client.code}.',
                actor=actor,
                client=locked_file.client,
                external_file=locked_file,
                metadata=import_summary,
                request=request,
            )

        return import_summary
    except Exception as exc:
        ExternalDataFile.objects.filter(pk=external_file.pk, status='VALIDATED').update(
            status='IMPORT_FAILED', error_message=str(exc)
        )
        create_audit_event(
            event_type='FTP_POSTCODES_ACTIVATION_FAILED',
            message=f'FTP postcodes activation failed for {external_file.client.code}: {exc}',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            severity='ERROR',
            metadata={
                'error_type': exc.__class__.__name__,
                'error_message': str(exc),
                'existing_rows_preserved': True,
            },
            request=request,
        )
        if isinstance(exc, PostcodesImportError):
            raise
        raise PostcodesImportError(str(exc)) from exc


def rollback_postcodes_file(external_file: ExternalDataFile, *, actor=None, request=None, reason='') -> dict:
    """Rollback only rows created by this activation. Historical/pre-existing rows are untouchable."""
    if external_file.file_type != 'SUBURBS':
        raise PostcodesImportError('Only SUBURBS files can be rolled back by this operation.')
    if external_file.status != 'ACTIVE':
        raise PostcodesImportError('Only the active postcodes file can be rolled back.')
    if not reason.strip():
        raise PostcodesImportError('A rollback reason is required.')

    created_rows = list((external_file.import_summary or {}).get('created_rows') or [])
    blockers = []
    for row in created_rows:
        suburb = str(row.get('suburb') or '').strip().upper()
        state = str(row.get('state') or '').strip().upper()
        postcode = str(row.get('postcode') or '').strip()
        carriers = sorted(set(
            FreightZone.objects.filter(
                suburb__iexact=suburb,
                state__iexact=state,
                postcode=postcode,
            ).values_list('carrier_service__carrier__code', flat=True)
        ))
        if carriers:
            blockers.append({
                'suburb': suburb,
                'state': state,
                'postcode': postcode,
                'carriers': carriers,
            })

    if blockers:
        sample = blockers[0]
        raise PostcodesImportError(
            'Rollback blocked because a row created by this activation is now referenced by operational '
            f'FreightZone data: {sample["suburb"]} {sample["state"]} {sample["postcode"]} '
            f'({", ".join(sample["carriers"])}).'
        )

    now = timezone.now()
    removed = 0
    missing = 0
    with transaction.atomic():
        locked_file = ExternalDataFile.objects.select_for_update().get(pk=external_file.pk)
        if locked_file.status != 'ACTIVE':
            raise PostcodesImportError('Postcodes snapshot is no longer ACTIVE.')

        for row in created_rows:
            query = Suburb.objects.select_for_update().filter(
                suburb_name=str(row.get('suburb') or '').strip().upper(),
                state=str(row.get('state') or '').strip().upper(),
                postcode=str(row.get('postcode') or '').strip(),
            )
            obj = query.first()
            if obj is None:
                missing += 1
                continue
            obj.delete()
            removed += 1

        locked_file.status = 'ROLLED_BACK'
        locked_file.rolled_back_by = actor if getattr(actor, 'is_authenticated', False) else None
        locked_file.rolled_back_at = now
        locked_file.import_summary = {
            **(locked_file.import_summary or {}),
            'rollback_reason': reason.strip(),
            'rolled_back_at': now.isoformat(),
            'created_rows_removed': removed,
            'created_rows_already_missing': missing,
        }
        locked_file.save(
            update_fields=['status', 'rolled_back_by', 'rolled_back_at', 'import_summary']
        )

        if locked_file.previous_active_file_id:
            ExternalDataFile.objects.filter(pk=locked_file.previous_active_file_id).update(status='ACTIVE')

        rollback_summary = {
            'created_rows_removed': removed,
            'created_rows_already_missing': missing,
            'historical_rows_modified': 0,
            'historical_rows_deleted': 0,
            'reason': reason.strip(),
        }
        create_audit_event(
            event_type='FTP_POSTCODES_ROLLED_BACK',
            message=f'FTP postcodes activation rolled back for {locked_file.client.code}.',
            actor=actor,
            client=locked_file.client,
            external_file=locked_file,
            severity='WARNING',
            metadata=rollback_summary,
            request=request,
        )

    return rollback_summary

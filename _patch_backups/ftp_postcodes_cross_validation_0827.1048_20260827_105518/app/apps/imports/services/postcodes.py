from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.imports.models import ExternalDataFile
from apps.imports.services.audit import create_audit_event
from apps.locations.models import Suburb


AUSTRALIAN_STATES = {'ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA'}
REQUIRED_COLUMNS = ('index', 'suburb', 'state', 'postcode')


class PostcodesImportError(Exception):
    pass


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


def snapshot_ftp_postcodes_file(*, client, filename='postcodes.csv', actor=None):
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
    )
    return external_file, True


def _decode(content: bytes) -> str:
    try:
        return content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise PostcodesImportError('Postcodes CSV must be UTF-8 encoded.') from exc


def parse_postcodes_rows(content: bytes):
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

        if source_index.upper() in seen_source_indexes:
            raise PostcodesImportError(
                f'Postcodes row {source_row} duplicates source index {source_index!r}.'
            )
        seen_source_indexes.add(source_index.upper())

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


def validate_postcodes_file(external_file: ExternalDataFile, actor=None) -> dict:
    if external_file.file_type != 'SUBURBS':
        raise PostcodesImportError('External file must have file_type SUBURBS.')
    path = external_file.local_path
    if not path:
        raise PostcodesImportError('External postcodes file has no local snapshot path.')

    content = Path(path).read_bytes()
    try:
        candidate_rows, excluded_rows = parse_postcodes_rows(content)

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
        would_add = sorted(candidate_set - current_set)
        current_not_in_source = sorted(current_set - candidate_set)

        suburb_state_counts = {}
        for suburb, state, postcode in candidate_set:
            key = (suburb, state)
            suburb_state_counts[key] = suburb_state_counts.get(key, 0) + 1
        multi_postcode_groups = sum(1 for count in suburb_state_counts.values() if count > 1)

        warnings = []
        if excluded_rows:
            warnings.append(
                f'{len(excluded_rows)} source row(s) are outside the Australian postcode candidate set '
                'and would be excluded from any future activation.'
            )
        if current_not_in_source:
            warnings.append(
                f'{len(current_not_in_source)} current Django suburb row(s) are not present in this source. '
                'Phase 1 does not delete them.'
            )

        summary = {
            'source_format': 'FTP_POSTCODES',
            'rows_read': len(candidate_rows) + len(excluded_rows),
            'candidate_rows': len(candidate_rows),
            'excluded_rows_count': len(excluded_rows),
            'existing_matches': len(existing_matches),
            'would_add': len(would_add),
            'current_not_in_source': len(current_not_in_source),
            'multi_postcode_suburb_state_groups': multi_postcode_groups,
            'excluded_rows': excluded_rows[:50],
            'would_add_preview': [
                {'suburb': suburb, 'state': state, 'postcode': postcode}
                for suburb, state, postcode in would_add[:50]
            ],
            'current_not_in_source_preview': [
                {'suburb': suburb, 'state': state, 'postcode': postcode}
                for suburb, state, postcode in current_not_in_source[:50]
            ],
            'warnings': warnings,
            'database_updated': False,
            'activation_available': False,
        }
    except PostcodesImportError as exc:
        external_file.status = 'VALIDATION_FAILED'
        external_file.error_message = str(exc)
        external_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
        external_file.validated_at = timezone.now()
        external_file.save(
            update_fields=['status', 'error_message', 'validated_by', 'validated_at']
        )
        create_audit_event(
            event_type='FTP_POSTCODES_VALIDATION_FAILED',
            message=f'FTP postcodes validation failed for {external_file.client.code}.',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            severity='ERROR',
            metadata={'error': str(exc), 'database_updated': False},
        )
        raise

    external_file.status = 'VALIDATED'
    external_file.validation_summary = summary
    external_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
    external_file.validated_at = timezone.now()
    external_file.error_message = ''
    external_file.save(
        update_fields=[
            'status',
            'validation_summary',
            'validated_by',
            'validated_at',
            'error_message',
        ]
    )
    create_audit_event(
        event_type='FTP_POSTCODES_VALIDATED',
        message=f'FTP postcodes snapshot validated for {external_file.client.code}.',
        actor=actor,
        client=external_file.client,
        external_file=external_file,
        metadata=summary,
    )
    return summary

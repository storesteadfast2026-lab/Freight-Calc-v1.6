from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.imports.models import ExternalDataFile
from apps.imports.services.audit import create_audit_event


DEFAULT_FTP_FILE_MAP = {
    'postcodes.csv': 'SUBURBS',
    'products.csv': 'PRODUCTS',
    'fuel.csv': 'FUEL',
    'zones.csv': 'ZONES',
    'stock.csv': 'STOCK',
}


class FtpInboxError(Exception):
    pass


def ftp_uploaded_data_root() -> Path:
    configured = str(getattr(settings, 'FTP_UPLOADED_DATA_DIR', '') or '').strip()
    if configured:
        return Path(configured).resolve()
    return (Path(settings.BASE_DIR) / 'uploaded_data').resolve()


def ftp_file_map() -> dict[str, str]:
    configured = getattr(settings, 'FTP_INBOX_FILE_MAP', None)
    if not configured:
        return dict(DEFAULT_FTP_FILE_MAP)
    return {
        str(filename).strip().lower(): str(file_type).strip().upper()
        for filename, file_type in dict(configured).items()
        if str(filename).strip() and str(file_type).strip()
    }


def calculate_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _display_local_timestamp(value) -> str:
    if not value:
        return ''
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, tz=timezone.get_current_timezone())
    elif timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return timezone.localtime(value).strftime('%d %b %Y %H:%M:%S')


def _latest_snapshot(*, client, file_type: str):
    return (
        ExternalDataFile.objects.filter(
            client=client,
            file_type=file_type,
            source_method='FTP_DROP',
        )
        .order_by('-uploaded_at', '-pk')
        .first()
    )


def inspect_ftp_inbox() -> dict:
    root = ftp_uploaded_data_root()
    mapping = ftp_file_map()
    result = {
        'root': str(root),
        'root_exists': root.exists() and root.is_dir(),
        'recognised': [],
        'missing': [],
        'ignored': [],
    }
    if not result['root_exists']:
        return result

    present = {p.name.lower(): p for p in root.iterdir() if p.is_file()}
    for filename, file_type in mapping.items():
        path = present.get(filename)
        if path is None:
            result['missing'].append(filename)
            continue
        content = path.read_bytes()
        stat = path.stat()
        result['recognised'].append({
            'filename': path.name,
            'file_type': file_type,
            'size_bytes': len(content),
            'sha256': calculate_sha256(content) if content else '',
            'empty': not bool(content),
            'source_modified_at': datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.get_current_timezone()
            ).isoformat(),
            'source_modified_at_display': _display_local_timestamp(stat.st_mtime),
        })

    known = set(mapping)
    result['ignored'] = sorted(
        path.name for key, path in present.items() if key not in known
    )
    return result


def _existing_snapshot(*, client, file_type: str, sha256: str):
    return (
        ExternalDataFile.objects.filter(
            client=client,
            file_type=file_type,
            source_method='FTP_DROP',
            sha256=sha256,
        )
        .order_by('-uploaded_at', '-pk')
        .first()
    )


@transaction.atomic
def _create_snapshot(*, client, file_type: str, source_path: Path, content: bytes, actor=None):
    digest = calculate_sha256(content)
    duplicate = _existing_snapshot(client=client, file_type=file_type, sha256=digest)
    if duplicate is not None:
        return duplicate, False

    external_file = ExternalDataFile(
        client=client,
        file_type=file_type,
        source_method='FTP_DROP',
        original_filename=source_path.name,
        stored_path='',
        file_size_bytes=len(content),
        mime_type=mimetypes.guess_type(source_path.name)[0] or 'application/octet-stream',
        sha256=digest,
        uploaded_by=actor if getattr(actor, 'is_authenticated', False) else None,
        status='UPLOADED',
    )
    external_file.uploaded_file.save(
        source_path.name,
        ContentFile(content),
        save=False,
    )
    external_file.save()
    external_file.stored_path = external_file.uploaded_file.name
    external_file.save(update_fields=['stored_path'])
    return external_file, True


def scan_ftp_inbox(*, client, actor=None, request=None) -> dict:
    inspection = inspect_ftp_inbox()
    if not inspection['root_exists']:
        raise FtpInboxError(
            f"FTP uploaded_data folder does not exist: {inspection['root']}"
        )

    root = Path(inspection['root'])
    checked_at = timezone.now()
    summary = {
        'root': inspection['root'],
        'checked_at': checked_at.isoformat(),
        'checked_at_display': _display_local_timestamp(checked_at),
        'recognised': 0,
        'new_snapshots': 0,
        'unchanged': 0,
        'errors': 0,
        'ignored': len(inspection['ignored']),
        'files': [],
        'database_updated_operationally': False,
    }

    for filename, file_type in ftp_file_map().items():
        source_path = root / filename
        if not source_path.exists() or not source_path.is_file():
            continue

        summary['recognised'] += 1
        try:
            stat = source_path.stat()
            content = source_path.read_bytes()
            if not content:
                raise FtpInboxError(f'{source_path.name} is empty.')

            previous_snapshot = _latest_snapshot(
                client=client, file_type=file_type
            )

            external_file, created = _create_snapshot(
                client=client,
                file_type=file_type,
                source_path=source_path,
                content=content,
                actor=actor,
            )
            if created:
                summary['new_snapshots'] += 1
                operation = 'NEW SNAPSHOT'
                create_audit_event(
                    event_type='FTP_INBOX_FILE_REGISTERED',
                    message=(
                        f'FTP inbox registered {source_path.name} '
                        f'as {file_type} for {client.code}.'
                    ),
                    actor=actor,
                    client=client,
                    external_file=external_file,
                    metadata={
                        'source_method': 'FTP_DROP',
                        'filename': source_path.name,
                        'file_type': file_type,
                        'sha256': external_file.sha256,
                        'file_size_bytes': external_file.file_size_bytes,
                        'operational_data_changed': False,
                    },
                    request=request,
                )
            else:
                summary['unchanged'] += 1
                operation = 'UNCHANGED'

            summary['files'].append({
                'filename': source_path.name,
                'file_type': file_type,
                'operation': operation,
                'result_label': 'NEW VERSION' if created else 'UNCHANGED',
                'action_label': (
                    f'Snapshot #{external_file.pk} created'
                    if created else 'No action required'
                ),
                'external_file_id': external_file.pk,
                'sha256': external_file.sha256,
                'sha_checked': True,
                'size_bytes': len(content),
                'size_display': (
                    f'{len(content) / (1024 * 1024):.1f} MB'
                    if len(content) >= 1024 * 1024
                    else f'{len(content) / 1024:.1f} KB'
                    if len(content) >= 1024
                    else f'{len(content)} B'
                ),
                'source_modified_at': datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.get_current_timezone()
                ).isoformat(),
                'source_modified_at_display': _display_local_timestamp(stat.st_mtime),
                'previous_snapshot_id': (
                    previous_snapshot.pk if previous_snapshot else None
                ),
                'previous_snapshot_at_display': (
                    _display_local_timestamp(previous_snapshot.uploaded_at)
                    if previous_snapshot else ''
                ),
                'matching_snapshot_id': (external_file.pk if not created else None),
            })
        except Exception as exc:
            summary['errors'] += 1
            summary['files'].append({
                'filename': source_path.name,
                'file_type': file_type,
                'operation': 'ERROR',
                'result_label': 'ERROR',
                'action_label': 'Review required',
                'sha_checked': False,
                'error': str(exc),
            })

    create_audit_event(
        event_type='FTP_INBOX_CHECKED',
        message=(
            f'FTP inbox checked for {client.code}: '
            f'{summary["recognised"]} recognised, '
            f'{summary["new_snapshots"]} new, '
            f'{summary["unchanged"]} unchanged, '
            f'{summary["errors"]} error(s).'
        ),
        actor=actor,
        client=client,
        severity='WARNING' if summary['errors'] else 'INFO',
        metadata=summary,
        request=request,
    )
    return summary

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile

from apps.imports.models import ExternalDataFile
from apps.imports.services.audit import create_audit_event
from apps.imports.services.fuel import FuelImportError, calculate_sha256


def uploaded_data_root() -> Path:
    configured = getattr(settings, 'FTP_UPLOADED_DATA_DIR', '')
    if configured:
        return Path(configured).resolve()
    return (Path(settings.BASE_DIR) / 'uploaded_data').resolve()


def resolve_uploaded_data_file(filename: str) -> Path:
    safe_name = Path(str(filename or '')).name
    if not safe_name or safe_name != str(filename or ''):
        raise FuelImportError('FTP filename must be a simple filename inside uploaded_data.')
    path = (uploaded_data_root() / safe_name).resolve()
    root = uploaded_data_root()
    if path.parent != root:
        raise FuelImportError('FTP source must be located directly inside uploaded_data.')
    if not path.exists() or not path.is_file():
        raise FuelImportError(f'FTP source file not found: {path}.')
    if path.suffix.lower() != '.csv':
        raise FuelImportError('FTP Fuel source must be a .csv file.')
    return path


def snapshot_ftp_fuel_file(*, client, filename='fuel.csv', actor=None) -> tuple[ExternalDataFile, bool]:
    """Create an immutable Django snapshot of one FTP Fuel drop.

    The source file is never deleted or modified. Identical FTP content already
    registered for the same client is returned instead of creating a duplicate
    snapshot, making repeated command runs idempotent.
    """
    source_path = resolve_uploaded_data_file(filename)
    content = source_path.read_bytes()
    if not content:
        raise FuelImportError('FTP Fuel source is empty.')

    digest = calculate_sha256(content)
    existing = (
        ExternalDataFile.objects.filter(
            client=client,
            file_type='FUEL',
            source_method='FTP_DROP',
            sha256=digest,
        )
        .order_by('-uploaded_at')
        .first()
    )
    if existing is not None:
        create_audit_event(
            event_type='FTP_FUEL_SNAPSHOT_SKIPPED',
            message=f'Identical FTP Fuel content already registered for {client.code}.',
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
        file_type='FUEL',
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
        event_type='FTP_FUEL_SNAPSHOT_CREATED',
        message=f'FTP Fuel snapshot created for {client.code}.',
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

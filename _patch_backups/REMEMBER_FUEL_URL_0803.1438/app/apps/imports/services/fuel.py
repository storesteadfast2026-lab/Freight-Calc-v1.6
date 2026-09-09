from __future__ import annotations

import csv
import hashlib
import io
import mimetypes
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.carriers.models import ClientCarrierConfig
from apps.imports.models import ExternalDataFile
from apps.imports.services.audit import create_audit_event


REQUIRED_COLUMNS = ('master_rate', 'info', 'rate', 'updated', 'expires', 'warnings')


class FuelImportError(Exception):
    """Raised when a fuel source cannot be downloaded, validated, activated or rolled back."""


@dataclass(frozen=True)
class FuelRateRow:
    line_number: int
    master_rate: str
    rate: Decimal
    info: str
    updated: date | None
    expires: date | None
    warnings: str


def normalize_ratecard(value) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        number = Decimal(text)
        if number == number.to_integral_value():
            return str(number.quantize(Decimal('1')))
    except InvalidOperation:
        pass
    return text.upper()


def parse_decimal_rate(value: str) -> Decimal:
    text = str(value or '').strip()
    if not text:
        raise FuelImportError('Fuel rate is empty.')
    is_percent = text.endswith('%')
    text = text.rstrip('%').strip()
    try:
        rate = Decimal(text)
    except InvalidOperation as exc:
        raise FuelImportError(f'Invalid fuel rate: {value!r}.') from exc
    if is_percent:
        rate = rate / Decimal('100')
    return rate


def parse_date(value: str) -> date | None:
    text = str(value or '').strip()
    if not text:
        return None
    formats = (
        '%Y-%m-%d',
        '%d/%m/%Y',
        '%d-%m-%Y',
        '%m/%d/%Y',
        '%Y/%m/%d',
        '%d %B %Y',
        '%d %b %Y',
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as exc:
        raise FuelImportError(f'Invalid date value: {value!r}.') from exc


def decode_csv_bytes(content: bytes) -> str:
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise FuelImportError('The fuel CSV is not valid UTF-8 or Windows-1252 text.')


def read_file_bytes(external_file: ExternalDataFile) -> bytes:
    if external_file.uploaded_file:
        external_file.uploaded_file.open('rb')
        try:
            return external_file.uploaded_file.read()
        finally:
            external_file.uploaded_file.close()
    if external_file.stored_path:
        path = Path(external_file.stored_path)
        if path.exists() and path.is_file():
            return path.read_bytes()
    raise FuelImportError('The stored fuel file is not available.')


def calculate_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def download_source(url: str) -> tuple[bytes, str]:
    timeout = int(getattr(settings, 'FUEL_FETCH_TIMEOUT_SECONDS', 30))
    request = Request(
        url,
        headers={
            'User-Agent': 'STH-Freight-Calculator/1.0',
            'Accept': 'text/csv,text/plain,*/*',
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read()
            content_type = response.headers.get_content_type() or 'text/csv'
    except HTTPError as exc:
        raise FuelImportError(f'Fuel source returned HTTP {exc.code}.') from exc
    except URLError as exc:
        raise FuelImportError(f'Could not connect to the fuel source: {exc.reason}.') from exc
    except TimeoutError as exc:
        raise FuelImportError('Fuel source request timed out.') from exc
    if not content:
        raise FuelImportError('Fuel source returned an empty file.')
    return content, content_type


def create_downloaded_fuel_file(*, client, actor, notes='', request=None) -> ExternalDataFile:
    source_url = getattr(settings, 'FUEL_SOURCE_URL', 'https://www.poscat.com.au/fuelsc/fuel.csv')
    request_id = hashlib.sha256(f'{timezone.now().isoformat()}:{client.pk}'.encode()).hexdigest()[:32]
    create_audit_event(
        event_type='FUEL_FETCH_STARTED',
        message=f'Fuel download started for {client.code}.',
        actor=actor,
        client=client,
        metadata={'source_url': source_url, 'source_method': 'ADMIN_WEB_FETCH'},
        request=request,
        request_id=request_id,
    )
    try:
        content, content_type = download_source(source_url)
        filename = Path(source_url).name or 'fuel.csv'
        external_file = ExternalDataFile(
            client=client,
            file_type='FUEL',
            source_method='ADMIN_WEB_FETCH',
            source_url=source_url,
            original_filename=filename,
            stored_path='',
            file_size_bytes=len(content),
            mime_type=content_type,
            sha256=calculate_sha256(content),
            notes=notes,
            uploaded_by=actor if getattr(actor, 'is_authenticated', False) else None,
            status='DOWNLOADED',
        )
        external_file.uploaded_file.save(filename, ContentFile(content), save=False)
        external_file.save()
        external_file.stored_path = external_file.uploaded_file.name
        external_file.save(update_fields=['stored_path'])
        create_audit_event(
            event_type='FUEL_FETCH_COMPLETED',
            message=f'Fuel file downloaded for {client.code}.',
            actor=actor,
            client=client,
            external_file=external_file,
            metadata={
                'source_url': source_url,
                'source_method': 'ADMIN_WEB_FETCH',
                'original_filename': filename,
                'stored_filename': external_file.uploaded_file.name,
                'file_size_bytes': len(content),
                'mime_type': content_type,
                'sha256': external_file.sha256,
            },
            request=request,
            request_id=request_id,
        )
        return external_file
    except Exception as exc:
        create_audit_event(
            event_type='FUEL_FETCH_FAILED',
            message=f'Fuel download failed for {client.code}: {exc}',
            actor=actor,
            client=client,
            severity='ERROR',
            metadata={
                'source_url': source_url,
                'source_method': 'ADMIN_WEB_FETCH',
                'error_type': exc.__class__.__name__,
                'error_message': str(exc),
                'database_updated': False,
            },
            request=request,
            request_id=request_id,
        )
        if isinstance(exc, FuelImportError):
            raise
        raise FuelImportError(str(exc)) from exc


def parse_fuel_rows(content: bytes) -> tuple[list[FuelRateRow], list[str]]:
    text = decode_csv_bytes(content)
    reader = csv.DictReader(io.StringIO(text))
    raw_headers = reader.fieldnames or []
    header_map = {str(header or '').strip().lower(): header for header in raw_headers}
    missing = [column for column in REQUIRED_COLUMNS if column not in header_map]
    if missing:
        raise FuelImportError(f'Missing required columns: {", ".join(missing)}.')

    rows: list[FuelRateRow] = []
    seen: set[str] = set()
    warnings: list[str] = []
    maximum_rate = Decimal(str(getattr(settings, 'FUEL_RATE_MAX', '1.0')))

    for line_number, raw in enumerate(reader, start=2):
        normalized = {
            key: str(raw.get(source_header, '') or '').strip()
            for key, source_header in header_map.items()
        }
        if not any(normalized.values()):
            continue
        ratecard = normalize_ratecard(normalized.get('master_rate'))
        if not ratecard:
            raise FuelImportError(f'Line {line_number}: master_rate is required.')
        if ratecard in seen:
            raise FuelImportError(f'Line {line_number}: duplicate master_rate {ratecard}.')
        seen.add(ratecard)
        try:
            rate = parse_decimal_rate(normalized.get('rate', ''))
        except FuelImportError as exc:
            raise FuelImportError(f'Line {line_number}: {exc}') from exc
        if rate < 0 or rate > maximum_rate:
            raise FuelImportError(
                f'Line {line_number}: rate {rate} is outside the allowed range 0 to {maximum_rate}.'
            )
        try:
            updated = parse_date(normalized.get('updated', ''))
            expires = parse_date(normalized.get('expires', ''))
        except FuelImportError as exc:
            raise FuelImportError(f'Line {line_number}: {exc}') from exc
        if updated and expires and expires < updated:
            raise FuelImportError(f'Line {line_number}: expires is earlier than updated.')
        row_warning = normalized.get('warnings', '')
        if row_warning and row_warning not in warnings:
            warnings.append(row_warning)
        rows.append(
            FuelRateRow(
                line_number=line_number,
                master_rate=ratecard,
                rate=rate,
                info=normalized.get('info', ''),
                updated=updated,
                expires=expires,
                warnings=row_warning,
            )
        )
    if not rows:
        raise FuelImportError('The fuel CSV does not contain any data rows.')
    return rows, warnings


def _source_dates(rows: Iterable[FuelRateRow]) -> tuple[date | None, date | None]:
    updated = next((row.updated for row in rows if row.updated), None)
    expires = next((row.expires for row in rows if row.expires), None)
    return updated, expires


def build_validation_summary(external_file: ExternalDataFile, rows: list[FuelRateRow], warnings: list[str]) -> dict:
    configs = list(
        ClientCarrierConfig.objects.filter(client=external_file.client)
        .select_related('carrier_service__carrier')
        .order_by('carrier_service__carrier__code', 'carrier_service__service_code')
    )
    rates_by_card = {row.master_rate: row for row in rows}
    configs_by_card: dict[str, list[ClientCarrierConfig]] = {}
    for config in configs:
        card = normalize_ratecard(config.ratecard)
        if card:
            configs_by_card.setdefault(card, []).append(config)

    preview = []
    updated_count = 0
    unchanged_count = 0
    for card, matching_configs in configs_by_card.items():
        row = rates_by_card.get(card)
        if row is None:
            continue
        for config in matching_configs:
            changed = config.fuel_levy != row.rate
            if changed:
                updated_count += 1
            else:
                unchanged_count += 1
            preview.append(
                {
                    'config_id': config.pk,
                    'carrier': config.carrier_service.carrier.code,
                    'service': config.carrier_service.service_code,
                    'ratecard': card,
                    'current_rate': str(config.fuel_levy),
                    'new_rate': str(row.rate),
                    'result': 'CHANGE' if changed else 'UNCHANGED',
                }
            )

    csv_cards = set(rates_by_card)
    django_cards = set(configs_by_card)
    duplicate_file = (
        ExternalDataFile.objects.filter(
            client=external_file.client, file_type='FUEL', sha256=external_file.sha256
        )
        .exclude(pk=external_file.pk)
        .order_by('-uploaded_at')
        .first()
    )
    updated, expires = _source_dates(rows)
    today = timezone.localdate()
    summary_warnings = list(warnings)
    if expires and expires < today:
        summary_warnings.append(f'Fuel dataset expired on {expires.isoformat()}.')

    return {
        'rows_received': len(rows),
        'rows_valid': len(rows),
        'rows_invalid': 0,
        'configs_to_update': updated_count,
        'configs_unchanged': unchanged_count,
        'ratecards_matched': sorted(csv_cards & django_cards),
        'ratecards_not_found_in_django': sorted(csv_cards - django_cards),
        'django_ratecards_missing_from_file': sorted(django_cards - csv_cards),
        'source_updated': updated.isoformat() if updated else None,
        'source_expires': expires.isoformat() if expires else None,
        'is_expired': bool(expires and expires < today),
        'duplicate_file_id': duplicate_file.pk if duplicate_file else None,
        'duplicate_file_status': duplicate_file.status if duplicate_file else None,
        'warnings': summary_warnings + ([f'Duplicate content already exists in file #{duplicate_file.pk}.'] if duplicate_file else []),
        'errors': [],
        'preview': preview,
    }


def validate_fuel_file(external_file: ExternalDataFile, *, actor=None, request=None) -> dict:
    if external_file.file_type != 'FUEL':
        raise FuelImportError('Only FUEL files can be validated by this operation.')
    request_id = hashlib.sha256(f'validate:{timezone.now().isoformat()}:{external_file.pk}'.encode()).hexdigest()[:32]
    try:
        content = read_file_bytes(external_file)
        calculated_hash = calculate_sha256(content)
        external_file.sha256 = calculated_hash
        rows, warnings = parse_fuel_rows(content)
        summary = build_validation_summary(external_file, rows, warnings)
        external_file.file_size_bytes = len(content)
        external_file.validation_summary = summary
        external_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
        external_file.validated_at = timezone.now()
        external_file.status = 'VALIDATED'
        external_file.error_message = ''
        external_file.save(
            update_fields=[
                'sha256', 'file_size_bytes', 'validation_summary', 'validated_by',
                'validated_at', 'status', 'error_message'
            ]
        )
        create_audit_event(
            event_type='FUEL_VALIDATION_PASSED',
            message=f'Fuel file validation passed for {external_file.client.code}.',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            metadata={
                'sha256': calculated_hash,
                **{key: value for key, value in summary.items() if key != 'preview'},
            },
            request=request,
            request_id=request_id,
        )
        return summary
    except Exception as exc:
        external_file.status = 'VALIDATION_FAILED'
        external_file.error_message = str(exc)
        external_file.validation_summary = {
            'rows_received': 0,
            'rows_valid': 0,
            'rows_invalid': 0,
            'warnings': [],
            'errors': [str(exc)],
        }
        external_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
        external_file.validated_at = timezone.now()
        external_file.save(
            update_fields=[
                'status', 'error_message', 'validation_summary', 'validated_by', 'validated_at'
            ]
        )
        create_audit_event(
            event_type='FUEL_VALIDATION_FAILED',
            message=f'Fuel file validation failed for {external_file.client.code}: {exc}',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            severity='ERROR',
            metadata={'error_type': exc.__class__.__name__, 'error_message': str(exc), 'database_updated': False},
            request=request,
            request_id=request_id,
        )
        if isinstance(exc, FuelImportError):
            raise
        raise FuelImportError(str(exc)) from exc


def _fuel_source_label(external_file: ExternalDataFile) -> str:
    return 'ADMIN_WEB_FETCH' if external_file.source_method == 'ADMIN_WEB_FETCH' else 'ADMIN_UPLOAD'


def activate_fuel_file(
    external_file: ExternalDataFile,
    *,
    actor=None,
    request=None,
    force_expired=False,
    justification='',
) -> dict:
    if external_file.status != 'VALIDATED':
        raise FuelImportError('Validate the fuel file before activation.')
    duplicate_active = (
        ExternalDataFile.objects.filter(
            client=external_file.client, file_type='FUEL', status='ACTIVE', sha256=external_file.sha256
        )
        .exclude(pk=external_file.pk)
        .first()
    )
    if duplicate_active:
        raise FuelImportError(
            f'This fuel file is identical to the active file #{duplicate_active.pk}; no activation is required.'
        )
    content = read_file_bytes(external_file)
    rows, _ = parse_fuel_rows(content)
    rates_by_card = {row.master_rate: row for row in rows}
    updated, expires = _source_dates(rows)
    if expires and expires < timezone.localdate():
        if not force_expired:
            raise FuelImportError(
                f'The fuel dataset expired on {expires.isoformat()}. Activation is blocked.'
            )
        if not getattr(actor, 'is_superuser', False):
            raise FuelImportError('Only a superuser can force activation of an expired fuel dataset.')
        if not justification.strip():
            raise FuelImportError('A justification is required to activate an expired fuel dataset.')

    request_id = hashlib.sha256(f'activate:{timezone.now().isoformat()}:{external_file.pk}'.encode()).hexdigest()[:32]
    now = timezone.now()
    changes = []
    matched_cards = set()

    try:
        with transaction.atomic():
            locked_file = ExternalDataFile.objects.select_for_update().get(pk=external_file.pk)
            # Lock only ClientCarrierConfig rows. Do not join the nullable
            # fuel_data_file relation in a SELECT ... FOR UPDATE query because
            # PostgreSQL rejects locking the nullable side of an OUTER JOIN.
            configs = list(
                ClientCarrierConfig.objects.select_for_update(of=('self',))
                .filter(client=locked_file.client)
                .select_related('carrier_service__carrier')
            )
            for config in configs:
                card = normalize_ratecard(config.ratecard)
                row = rates_by_card.get(card)
                if row is None:
                    continue
                matched_cards.add(card)
                old_source_file_id = config.fuel_data_file_id
                change = {
                    'carrier': config.carrier_service.carrier.code,
                    'service': config.carrier_service.service_code,
                    'ratecard': card,
                    'old_rate': str(config.fuel_levy),
                    'new_rate': str(row.rate),
                    'old_source': config.fuel_levy_source,
                    'new_source': _fuel_source_label(locked_file),
                    'old_source_file_id': old_source_file_id,
                    'old_updated_at': config.fuel_levy_updated_at.isoformat() if config.fuel_levy_updated_at else None,
                    'changed': config.fuel_levy != row.rate,
                }
                changes.append(change)
                config.fuel_levy = row.rate
                config.fuel_levy_source = _fuel_source_label(locked_file)
                config.fuel_levy_updated_at = now
                config.fuel_data_file = locked_file
                config.save(
                    update_fields=['fuel_levy', 'fuel_levy_source', 'fuel_levy_updated_at', 'fuel_data_file']
                )

            if not changes:
                raise FuelImportError('No Client carrier configs matched the ratecards in this fuel file.')

            previous_active = (
                ExternalDataFile.objects.select_for_update()
                .filter(client=locked_file.client, file_type='FUEL', status='ACTIVE')
                .exclude(pk=locked_file.pk)
                .first()
            )
            if previous_active:
                previous_active.status = 'ARCHIVED'
                previous_active.save(update_fields=['status'])

            changed_count = sum(1 for change in changes if change['changed'])
            unchanged_count = len(changes) - changed_count
            summary = {
                'rows_received': len(rows),
                'configs_matched': len(changes),
                'configs_updated': changed_count,
                'configs_unchanged': unchanged_count,
                'ratecards_not_found_in_django': sorted(set(rates_by_card) - matched_cards),
                'source_updated': updated.isoformat() if updated else None,
                'source_expires': expires.isoformat() if expires else None,
                'forced_expired_activation': bool(force_expired and expires and expires < timezone.localdate()),
                'force_justification': justification.strip(),
                'previous_active_file_id': previous_active.pk if previous_active else None,
                'changes': changes,
            }
            locked_file.previous_active_file = previous_active
            locked_file.status = 'ACTIVE'
            locked_file.imported_by = actor if getattr(actor, 'is_authenticated', False) else None
            locked_file.last_imported_at = now
            locked_file.activated_by = actor if getattr(actor, 'is_authenticated', False) else None
            locked_file.activated_at = now
            locked_file.import_summary = summary
            locked_file.error_message = ''
            locked_file.save(
                update_fields=[
                    'previous_active_file', 'status', 'imported_by', 'last_imported_at',
                    'activated_by', 'activated_at', 'import_summary', 'error_message'
                ]
            )
            create_audit_event(
                event_type='FUEL_IMPORT_ACTIVATED',
                message=f'Fuel rates activated for {locked_file.client.code}.',
                actor=actor,
                client=locked_file.client,
                external_file=locked_file,
                metadata={key: value for key, value in summary.items() if key != 'changes'} | {
                    'changes': changes,
                    'sha256': locked_file.sha256,
                    'source_method': locked_file.source_method,
                    'source_url': locked_file.source_url,
                },
                request=request,
                request_id=request_id,
            )

        return summary
    except Exception as exc:
        ExternalDataFile.objects.filter(pk=external_file.pk).update(
            status='IMPORT_FAILED', error_message=str(exc)
        )
        create_audit_event(
            event_type='FUEL_IMPORT_FAILED',
            message=f'Fuel activation failed for {external_file.client.code}: {exc}',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            severity='ERROR',
            metadata={
                'error_type': exc.__class__.__name__,
                'error_message': str(exc),
                'previous_dataset_preserved': True,
                'database_updated': False,
            },
            request=request,
            request_id=request_id,
        )
        if isinstance(exc, FuelImportError):
            raise
        raise FuelImportError(str(exc)) from exc


def rollback_fuel_file(external_file: ExternalDataFile, *, actor=None, request=None, reason='') -> dict:
    if external_file.status != 'ACTIVE':
        raise FuelImportError('Only the active fuel file can be rolled back.')
    if not reason.strip():
        raise FuelImportError('A rollback reason is required.')
    changes = list((external_file.import_summary or {}).get('changes') or [])
    if not changes:
        raise FuelImportError('No previous fuel values are stored for this file.')

    request_id = hashlib.sha256(f'rollback:{timezone.now().isoformat()}:{external_file.pk}'.encode()).hexdigest()[:32]
    restored = 0
    now = timezone.now()
    with transaction.atomic():
        locked_file = ExternalDataFile.objects.select_for_update().get(pk=external_file.pk)
        for change in changes:
            config = (
                ClientCarrierConfig.objects.select_for_update()
                .filter(
                    client=locked_file.client,
                    carrier_service__carrier__code=change['carrier'],
                    carrier_service__service_code=change['service'],
                    ratecard=change['ratecard'],
                )
                .first()
            )
            if config is None:
                raise FuelImportError(
                    f'Cannot rollback {change["carrier"]} {change["service"]}: configuration not found.'
                )
            if config.fuel_levy != Decimal(change['new_rate']):
                raise FuelImportError(
                    f'Cannot rollback {change["carrier"]} {change["service"]}: fuel rate changed after activation.'
                )
            config.fuel_levy = Decimal(change['old_rate'])
            config.fuel_levy_source = change.get('old_source') or 'LEGACY_WORKBOOK'
            old_updated_at = change.get('old_updated_at')
            config.fuel_levy_updated_at = datetime.fromisoformat(old_updated_at) if old_updated_at else None
            config.fuel_data_file_id = change.get('old_source_file_id')
            config.save(
                update_fields=['fuel_levy', 'fuel_levy_source', 'fuel_levy_updated_at', 'fuel_data_file']
            )
            restored += 1

        locked_file.status = 'ROLLED_BACK'
        locked_file.rolled_back_by = actor if getattr(actor, 'is_authenticated', False) else None
        locked_file.rolled_back_at = now
        locked_file.import_summary = {
            **(locked_file.import_summary or {}),
            'rollback_reason': reason.strip(),
            'rolled_back_at': now.isoformat(),
            'configs_restored': restored,
        }
        locked_file.save(
            update_fields=['status', 'rolled_back_by', 'rolled_back_at', 'import_summary']
        )
        if locked_file.previous_active_file_id:
            ExternalDataFile.objects.filter(pk=locked_file.previous_active_file_id).update(status='ACTIVE')

        summary = {'configs_restored': restored, 'reason': reason.strip()}
        create_audit_event(
            event_type='FUEL_IMPORT_ROLLED_BACK',
            message=f'Fuel rates rolled back for {locked_file.client.code}.',
            actor=actor,
            client=locked_file.client,
            external_file=locked_file,
            severity='WARNING',
            metadata=summary,
            request=request,
            request_id=request_id,
        )

    return summary


def reapply_active_fuel_rates(client) -> dict:
    """Reapply the active web/admin fuel dataset after a workbook --replace import."""
    active_file = (
        ExternalDataFile.objects.filter(client=client, file_type='FUEL', status='ACTIVE')
        .order_by('-activated_at', '-uploaded_at')
        .first()
    )
    if active_file is None:
        return {'active_fuel_file_id': None, 'configs_reapplied': 0}
    rows, _ = parse_fuel_rows(read_file_bytes(active_file))
    rates_by_card = {row.master_rate: row.rate for row in rows}
    configs = list(ClientCarrierConfig.objects.filter(client=client))
    now = timezone.now()
    reapplied = 0
    for config in configs:
        rate = rates_by_card.get(normalize_ratecard(config.ratecard))
        if rate is None:
            continue
        config.fuel_levy = rate
        config.fuel_levy_source = _fuel_source_label(active_file)
        config.fuel_levy_updated_at = now
        config.fuel_data_file = active_file
        config.save(
            update_fields=['fuel_levy', 'fuel_levy_source', 'fuel_levy_updated_at', 'fuel_data_file']
        )
        reapplied += 1
    return {'active_fuel_file_id': active_file.pk, 'configs_reapplied': reapplied}

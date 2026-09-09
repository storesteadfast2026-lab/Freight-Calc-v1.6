from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Q
from django.utils import timezone

from apps.carriers.models import ClientCarrierConfig
from apps.imports.models import ExternalDataFile
from apps.imports.services.audit import create_audit_event
from apps.imports.services.fuel import calculate_sha256
from apps.locations.models import Suburb
from apps.rates.models import FreightRate, FreightZone


REQUIRED_COLUMNS = (
    'index', 'index2', 'carrier', 'suburb', 'state', 'postcode', 'zone', 'subzone', 'area'
)
AUSTRALIAN_STATES = {'ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA'}
VALIDATION_VERSION = 1


class ZonesImportError(Exception):
    pass


def _s(value) -> str:
    return str(value or '').strip()


def _u(value) -> str:
    return _s(value).upper()


def uploaded_data_root() -> Path:
    configured = getattr(settings, 'FTP_UPLOADED_DATA_DIR', '')
    if configured:
        return Path(configured).resolve()
    return (Path(settings.BASE_DIR) / 'uploaded_data').resolve()


def resolve_uploaded_zones_file(filename: str) -> Path:
    safe_name = Path(str(filename or '')).name
    if not safe_name or safe_name != str(filename or ''):
        raise ZonesImportError('FTP filename must be a simple filename inside uploaded_data.')
    root = uploaded_data_root()
    path = (root / safe_name).resolve()
    if path.parent != root:
        raise ZonesImportError('FTP Zones source must be located directly inside uploaded_data.')
    if not path.exists() or not path.is_file():
        raise ZonesImportError(f'FTP Zones source file not found: {path}.')
    if path.suffix.lower() != '.csv':
        raise ZonesImportError('FTP Zones source must be a .csv file.')
    return path


def snapshot_ftp_zones_file(*, client, filename='zones.csv', actor=None):
    """Snapshot one zones.csv drop without modifying or deleting the FTP source."""
    source_path = resolve_uploaded_zones_file(filename)
    content = source_path.read_bytes()
    if not content:
        raise ZonesImportError('FTP Zones source is empty.')

    digest = calculate_sha256(content)
    existing = (
        ExternalDataFile.objects.filter(
            client=client,
            file_type='ZONES',
            source_method='FTP_DROP',
            sha256=digest,
        )
        .order_by('-uploaded_at')
        .first()
    )
    if existing is not None:
        create_audit_event(
            event_type='FTP_ZONES_SNAPSHOT_SKIPPED',
            message=f'Identical FTP Zones content already registered for {client.code}.',
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
        file_type='ZONES',
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
        event_type='FTP_ZONES_SNAPSHOT_CREATED',
        message=f'FTP Zones snapshot created for {client.code}.',
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


def parse_zones_rows(content: bytes):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ZonesImportError(f'Zones CSV is not valid UTF-8: {exc}') from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ZonesImportError('Zones CSV has no header row.')
    fieldnames = [str(value or '').strip() for value in reader.fieldnames]
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ZonesImportError(f'Zones CSV missing required column(s): {", ".join(missing)}.')

    rows = []
    duplicates = []
    seen_full = set()
    non_au = []
    short_postcodes = []

    for source_row, raw in enumerate(reader, start=2):
        item = {column: _u(raw.get(column)) for column in REQUIRED_COLUMNS}
        item['postcode'] = _s(raw.get('postcode'))
        item['source_row'] = source_row

        if not item['carrier'] or not item['suburb'] or not item['state'] or not item['zone']:
            raise ZonesImportError(
                f'Zones row {source_row} has a blank required value for carrier/suburb/state/zone.'
            )

        expected_index = f"{item['carrier']}{item['suburb']}{item['state']}"
        if item['index'] != expected_index:
            raise ZonesImportError(
                f"Zones row {source_row} index mismatch: {item['index']!r} != {expected_index!r}."
            )
        expected_index2 = f"{item['carrier']}{item['zone']}"
        if item['index2'] != expected_index2:
            raise ZonesImportError(
                f"Zones row {source_row} index2 mismatch: {item['index2']!r} != {expected_index2!r}."
            )

        full_key = tuple(item[column] for column in REQUIRED_COLUMNS)
        if full_key in seen_full:
            if len(duplicates) < 100:
                duplicates.append({
                    'source_row': source_row,
                    'carrier': item['carrier'],
                    'suburb': item['suburb'],
                    'state': item['state'],
                    'postcode': item['postcode'],
                    'zone': item['zone'],
                    'subzone': item['subzone'],
                    'area': item['area'],
                })
            continue
        seen_full.add(full_key)

        if item['state'] not in AUSTRALIAN_STATES:
            if len(non_au) < 100:
                non_au.append({
                    'source_row': source_row,
                    'carrier': item['carrier'],
                    'suburb': item['suburb'],
                    'state': item['state'],
                    'postcode': item['postcode'],
                    'zone': item['zone'],
                })
            item['non_australian'] = True
        else:
            item['non_australian'] = False

        postcode = item['postcode']
        if item['state'] in AUSTRALIAN_STATES and (not postcode.isdigit() or len(postcode) != 4):
            if len(short_postcodes) < 100:
                short_postcodes.append({
                    'source_row': source_row,
                    'carrier': item['carrier'],
                    'suburb': item['suburb'],
                    'state': item['state'],
                    'postcode': postcode,
                    'zone': item['zone'],
                    'reason': 'Australian postcode is not exactly four digits in source',
                })
            item['postcode_format_review'] = True
        else:
            item['postcode_format_review'] = False

        rows.append(item)

    if not rows:
        raise ZonesImportError('Zones CSV contains no usable rows.')
    return rows, {
        'exact_duplicate_rows_ignored': len(seen_full) + len(duplicates) - len(seen_full),
        'duplicate_preview': duplicates,
        'non_au_preview': non_au,
        'postcode_format_preview': short_postcodes,
    }


def _mapping_for_client(client):
    configs = list(
        ClientCarrierConfig.objects.filter(client=client)
        .select_related('carrier_service__carrier')
    )
    config_by_carrier = defaultdict(list)
    for config in configs:
        config_by_carrier[_u(config.carrier_service.carrier.code)].append(config)

    existing_zone_services = defaultdict(set)
    for carrier, service in (
        FreightZone.objects.filter(client=client)
        .values_list('carrier_service__carrier__code', 'carrier_service__service_code')
        .distinct()
    ):
        existing_zone_services[_u(carrier)].add(_u(service))

    result = {}
    for carrier, carrier_configs in config_by_carrier.items():
        zone_enabled = {
            _u(config.carrier_service.service_code)
            for config in carrier_configs
            if config.zone_enabled or config.postcode_zones_enabled
        }
        all_services = {_u(config.carrier_service.service_code) for config in carrier_configs}
        existing = existing_zone_services.get(carrier, set())

        chosen = None
        basis = ''
        if len(zone_enabled) == 1:
            chosen = next(iter(zone_enabled))
            basis = 'single configured zone-enabled service'
        elif len(all_services) == 1:
            chosen = next(iter(all_services))
            basis = 'single configured service'
        elif len(existing) == 1:
            chosen = next(iter(existing))
            basis = 'single existing FreightZone service'

        result[carrier] = {
            'service_code': chosen,
            'basis': basis,
            'configured_services': sorted(all_services),
            'zone_enabled_services': sorted(zone_enabled),
            'existing_zone_services': sorted(existing),
            'ambiguous': chosen is None,
        }
    return result


def validate_zones_file(external_file: ExternalDataFile, actor=None) -> dict:
    if external_file.file_type != 'ZONES':
        raise ZonesImportError('External file must have file_type ZONES.')
    path = external_file.local_path
    if not path:
        raise ZonesImportError('External Zones file has no local snapshot path.')

    content = Path(path).read_bytes()
    try:
        parsed_rows, parse_notes = parse_zones_rows(content)

        # Count duplicates exactly from the original CSV without storing them all.
        text = content.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        full_counter = Counter()
        for raw in reader:
            full_counter[tuple(_u(raw.get(column)) if column != 'postcode' else _s(raw.get(column)) for column in REQUIRED_COLUMNS)] += 1
        duplicate_extra_count = sum(count - 1 for count in full_counter.values() if count > 1)
        duplicate_group_count = sum(1 for count in full_counter.values() if count > 1)

        mappings = _mapping_for_client(external_file.client)
        configured_carriers = set(mappings)

        suburb_set = {
            (_u(suburb), _u(state), _s(postcode))
            for suburb, state, postcode in Suburb.objects.values_list('suburb_name', 'state', 'postcode')
        }

        services_by_pair = {
            (_u(carrier), _u(service)): service_id
            for service_id, carrier, service in (
                ClientCarrierConfig.objects.filter(client=external_file.client)
                .values_list(
                    'carrier_service_id',
                    'carrier_service__carrier__code',
                    'carrier_service__service_code',
                )
            )
        }

        existing_rows = list(
            FreightZone.objects.filter(client=external_file.client)
            .values_list(
                'carrier_service_id',
                'carrier_service__carrier__code',
                'carrier_service__service_code',
                'suburb', 'state', 'postcode', 'zone', 'subzone', 'area',
            )
        )
        existing_full = set()
        existing_by_location = defaultdict(set)
        existing_relevant_by_service = defaultdict(set)
        for service_id, carrier, service, suburb, state, postcode, zone, subzone, area in existing_rows:
            carrier = _u(carrier)
            service = _u(service)
            key = (
                service_id, _u(suburb), _u(state), _s(postcode),
                _u(zone), _u(subzone), _u(area),
            )
            existing_full.add(key)
            existing_by_location[(service_id, _u(suburb), _u(state), _s(postcode))].add(
                (_u(zone), _u(subzone), _u(area))
            )
            if carrier in configured_carriers:
                existing_relevant_by_service[service_id].add(key)

        rate_zone_set = {
            (service_id, _u(zone))
            for service_id, zone in FreightRate.objects.filter(client=external_file.client)
            .values_list('carrier_service_id', 'zone')
        }

        counts = Counter()
        per_carrier = defaultdict(Counter)
        preview = []
        source_full_by_service = defaultdict(set)

        for row in parsed_rows:
            carrier = row['carrier']
            if carrier not in configured_carriers:
                counts['irrelevant_source_rows'] += 1
                continue
            counts['relevant_source_rows'] += 1
            per_carrier[carrier]['source_rows'] += 1

            if row['non_australian']:
                counts['review_non_australian'] += 1
                per_carrier[carrier]['review'] += 1
                if len(preview) < 100:
                    preview.append({**row, 'service': '-', 'decision': 'REVIEW_NON_AU_STATE', 'reason': 'State is outside the Australian Suburb lookup scope.'})
                continue

            mapping = mappings[carrier]
            if mapping['ambiguous']:
                counts['review_service_mapping'] += 1
                per_carrier[carrier]['review'] += 1
                if len(preview) < 100:
                    preview.append({**row, 'service': '-', 'decision': 'REVIEW_SERVICE_MAPPING', 'reason': 'Source has no service column and Django service mapping is ambiguous.'})
                continue

            service_code = mapping['service_code']
            service_id = services_by_pair.get((carrier, service_code))
            if not service_id:
                counts['review_service_mapping'] += 1
                per_carrier[carrier]['review'] += 1
                if len(preview) < 100:
                    preview.append({**row, 'service': service_code, 'decision': 'REVIEW_SERVICE_MAPPING', 'reason': 'Mapped service is not configured for the client.'})
                continue

            source_key = (
                service_id, row['suburb'], row['state'], row['postcode'],
                row['zone'], row['subzone'], row['area'],
            )
            source_full_by_service[service_id].add(source_key)

            if source_key in existing_full:
                counts['exact_matches'] += 1
                per_carrier[carrier]['exact'] += 1
                continue

            location_key = (service_id, row['suburb'], row['state'], row['postcode'])
            previous_values = sorted(existing_by_location.get(location_key, set()))
            decision = 'CANDIDATE_CHANGE' if previous_values else 'CANDIDATE_ADD'
            reason = 'Existing location has different zone/subzone/area values.' if previous_values else 'Source location is not currently present in Django FreightZone.'

            if row['postcode_format_review']:
                decision = 'REVIEW_POSTCODE_FORMAT'
                reason = 'Australian postcode is not exactly four digits in the source. It will not be auto-padded.'
            elif (row['suburb'], row['state'], row['postcode']) not in suburb_set:
                decision = 'REVIEW_SUBURB_REFERENCE'
                reason = 'No exact Suburb + State + Postcode exists in the current Django Suburb lookup.'
            elif (service_id, row['zone']) not in rate_zone_set:
                decision = 'REVIEW_NO_RATE_ZONE'
                reason = 'No current FreightRate uses this mapped service and zone.'

            if decision == 'CANDIDATE_ADD':
                counts['candidate_add'] += 1
                per_carrier[carrier]['candidate_add'] += 1
            elif decision == 'CANDIDATE_CHANGE':
                counts['candidate_change'] += 1
                per_carrier[carrier]['candidate_change'] += 1
            else:
                counts['review'] += 1
                counts[decision.lower()] += 1
                per_carrier[carrier]['review'] += 1

            if len(preview) < 100:
                preview.append({
                    'source_row': row['source_row'],
                    'carrier': carrier,
                    'service': service_code,
                    'suburb': row['suburb'],
                    'state': row['state'],
                    'postcode': row['postcode'],
                    'zone': row['zone'],
                    'subzone': row['subzone'],
                    'area': row['area'],
                    'decision': decision,
                    'reason': reason,
                    'current_values': [
                        {'zone': z, 'subzone': sz, 'area': a}
                        for z, sz, a in previous_values[:5]
                    ],
                })

        current_not_in_source = 0
        for service_id, current_rows in existing_relevant_by_service.items():
            source_rows = source_full_by_service.get(service_id, set())
            current_not_in_source += len(current_rows - source_rows)

        mapping_preview = []
        for carrier in sorted(configured_carriers):
            data = mappings[carrier]
            mapping_preview.append({
                'carrier': carrier,
                'service': data['service_code'] or '-',
                'basis': data['basis'] or 'AMBIGUOUS',
                'configured_services': data['configured_services'],
                'zone_enabled_services': data['zone_enabled_services'],
                'existing_zone_services': data['existing_zone_services'],
                'ambiguous': data['ambiguous'],
            })

        warnings = []
        if duplicate_extra_count:
            warnings.append(f'{duplicate_extra_count} exact duplicate source row(s) would be de-duplicated for comparison; no data is changed.')
        non_au_count = sum(1 for row in parsed_rows if row['non_australian'])
        if non_au_count:
            warnings.append(f'{non_au_count} unique source row(s) use non-Australian states and remain review/excluded from Australian activation.')
        postcode_review_count = sum(1 for row in parsed_rows if row['postcode_format_review'])
        if postcode_review_count:
            warnings.append(f'{postcode_review_count} unique Australian source row(s) have non-four-digit postcodes; values are not auto-padded.')
        if current_not_in_source:
            warnings.append(f'{current_not_in_source} current relevant Django FreightZone row(s) are not represented by the safely mapped source comparison. They remain PRESERVE EXISTING in this phase.')
        if any(item['ambiguous'] for item in mapping_preview):
            warnings.append('At least one configured carrier cannot be safely mapped because zones.csv has no service column.')

        summary = {
            'source_format': 'FTP_ZONES',
            'validation_version': VALIDATION_VERSION,
            'rows_read': sum(full_counter.values()),
            'unique_rows': len(full_counter),
            'exact_duplicate_extra_rows': duplicate_extra_count,
            'exact_duplicate_groups': duplicate_group_count,
            'australian_unique_rows': sum(1 for row in parsed_rows if not row['non_australian']),
            'non_australian_unique_rows': non_au_count,
            'australian_postcode_format_review_rows': postcode_review_count,
            'configured_carriers': len(configured_carriers),
            'relevant_source_rows': counts['relevant_source_rows'],
            'irrelevant_source_rows': counts['irrelevant_source_rows'],
            'exact_matches': counts['exact_matches'],
            'candidate_add': counts['candidate_add'],
            'candidate_change': counts['candidate_change'],
            'review_total': counts['review'] + counts['review_non_australian'] + counts['review_service_mapping'],
            'review_non_australian': counts['review_non_australian'],
            'review_service_mapping': counts['review_service_mapping'],
            'review_postcode_format': counts['review_postcode_format'],
            'review_suburb_reference': counts['review_suburb_reference'],
            'review_no_rate_zone': counts['review_no_rate_zone'],
            'current_relevant_not_in_source': current_not_in_source,
            'service_mapping_preview': mapping_preview,
            'carrier_summary': [
                {
                    'carrier': carrier,
                    'source_rows': values['source_rows'],
                    'exact': values['exact'],
                    'candidate_add': values['candidate_add'],
                    'candidate_change': values['candidate_change'],
                    'review': values['review'],
                }
                for carrier, values in sorted(per_carrier.items())
            ],
            'delta_preview': preview,
            'duplicate_preview': parse_notes['duplicate_preview'],
            'non_au_preview': parse_notes['non_au_preview'],
            'postcode_format_preview': parse_notes['postcode_format_preview'],
            'warnings': warnings,
            'database_updated': False,
        }

        external_file.status = 'VALIDATED'
        external_file.validation_summary = summary
        external_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
        external_file.validated_at = timezone.now()
        external_file.error_message = ''
        external_file.save(update_fields=['status', 'validation_summary', 'validated_by', 'validated_at', 'error_message'])

        create_audit_event(
            event_type='FTP_ZONES_VALIDATED',
            message=f'FTP Zones file #{external_file.pk} validated for {external_file.client.code}.',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            metadata={
                'rows_read': summary['rows_read'],
                'relevant_source_rows': summary['relevant_source_rows'],
                'exact_matches': summary['exact_matches'],
                'candidate_add': summary['candidate_add'],
                'candidate_change': summary['candidate_change'],
                'review_total': summary['review_total'],
                'database_updated': False,
            },
        )
        return summary
    except Exception as exc:
        external_file.status = 'VALIDATION_FAILED'
        external_file.error_message = str(exc)
        external_file.validation_summary = {'source_format': 'FTP_ZONES', 'database_updated': False, 'error': str(exc)}
        external_file.validated_by = actor if getattr(actor, 'is_authenticated', False) else None
        external_file.validated_at = timezone.now()
        external_file.save(update_fields=['status', 'error_message', 'validation_summary', 'validated_by', 'validated_at'])
        create_audit_event(
            event_type='FTP_ZONES_VALIDATION_FAILED',
            message=f'FTP Zones validation failed for {external_file.client.code}: {exc}',
            actor=actor,
            client=external_file.client,
            external_file=external_file,
            severity='ERROR',
            metadata={'database_updated': False, 'error': str(exc)},
        )
        if isinstance(exc, ZonesImportError):
            raise
        raise ZonesImportError(str(exc)) from exc

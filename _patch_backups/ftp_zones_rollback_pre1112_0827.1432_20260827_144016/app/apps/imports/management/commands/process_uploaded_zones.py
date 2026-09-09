from django.core.management.base import BaseCommand, CommandError

from apps.clients.models import Client
from apps.imports.services.zones import (
    VALIDATION_VERSION,
    ZonesImportError,
    snapshot_ftp_zones_file,
    validate_zones_file,
)


class Command(BaseCommand):
    help = 'Snapshot and validate uploaded_data/zones.csv without changing operational FreightZone data.'

    def add_arguments(self, parser):
        parser.add_argument('--client', default='STH')
        parser.add_argument('--filename', default='zones.csv')

    def handle(self, *args, **options):
        try:
            client = Client.objects.get(code=options['client'])
        except Client.DoesNotExist as exc:
            raise CommandError(f"Client {options['client']!r} does not exist.") from exc

        try:
            external_file, created = snapshot_ftp_zones_file(
                client=client,
                filename=options['filename'],
            )
            if created:
                self.stdout.write(f'FTP Zones snapshot created as file #{external_file.pk}.')
            else:
                self.stdout.write(
                    f'No new snapshot created. Identical content is already file #{external_file.pk} with status {external_file.status}.'
                )

            summary = external_file.validation_summary or {}
            reusable = (
                external_file.status == 'VALIDATED'
                and summary.get('source_format') == 'FTP_ZONES'
                and summary.get('validation_version') == VALIDATION_VERSION
            )
            if reusable:
                self.stdout.write('Reusing the existing Zones validation summary for review.')
            else:
                if not created:
                    self.stdout.write('Existing summary is missing the current Zones validation version; re-validating the immutable snapshot.')
                summary = validate_zones_file(external_file)

            self.stdout.write(f'FTP Zones file #{external_file.pk} validated.')
            self.stdout.write('Source format: FTP_ZONES')
            self.stdout.write(f"Rows read: {summary['rows_read']}")
            self.stdout.write(f"Unique rows: {summary['unique_rows']}")
            self.stdout.write(f"Exact duplicate extra rows: {summary['exact_duplicate_extra_rows']}")
            self.stdout.write(f"Australian unique rows: {summary['australian_unique_rows']}")
            self.stdout.write(f"Non-Australian unique rows: {summary['non_australian_unique_rows']}")
            self.stdout.write(f"Australian postcode-format review rows: {summary['australian_postcode_format_review_rows']}")
            self.stdout.write(f"Configured client carriers: {summary['configured_carriers']}")
            self.stdout.write(f"Relevant source rows: {summary['relevant_source_rows']}")
            self.stdout.write(f"Source rows not used by this client: {summary['irrelevant_source_rows']}")
            self.stdout.write(f"Service resolution rule: {summary.get('service_resolution_rule', 'RATE_DRIVEN_EXPANSION')}")
            self.stdout.write(f"Derived service-zone comparisons: {summary.get('derived_service_rows', 0)}")
            self.stdout.write(f"Source rows expanded to multiple services: {summary.get('multi_service_source_rows', 0)}")
            self.stdout.write(f"Exact current FreightZone matches: {summary['exact_matches']}")
            self.stdout.write(f"Candidate additions: {summary['candidate_add']}")
            self.stdout.write(f"Candidate changes: {summary['candidate_change']}")
            self.stdout.write(f"Rows requiring review: {summary['review_total']}")
            self.stdout.write(f"Current relevant rows not safely represented by source: {summary['current_relevant_not_in_source']}")
            self.stdout.write(f"  Source-present locations with routing differences: {summary.get('current_detail_diff', 0)}")
            self.stdout.write(f"  Locations absent from safely mapped source: {summary.get('current_location_absent', 0)}")

            self.stdout.write('')
            self.stdout.write('CARRIER -> SERVICES (RATE-DRIVEN)')
            self.stdout.write('zones.csv intentionally has no service column. Each source zone is expanded only to configured services that have a current FreightRate for that zone.')
            for row in summary.get('service_mapping_preview', []):
                service_text = ', '.join(
                    f"{item['service']}[ratecard={item['ratecard'] or '-'}, rate-zones={item['rate_zone_count']}]"
                    for item in row.get('services', [])
                ) or '-'
                self.stdout.write(f"{row['carrier']:<8}  {service_text}")

            self.stdout.write('')
            self.stdout.write('RELEVANT CARRIER DELTA SUMMARY')
            self.stdout.write('Carrier   Source   Derived     Exact      Add     Change    Review')
            self.stdout.write('--------  -------  --------  --------  --------  --------  --------')
            for row in summary.get('carrier_summary', []):
                self.stdout.write(
                    f"{row['carrier']:<8}  {row['source_rows']:>7}  {row.get('derived_rows', 0):>8}  {row['exact']:>8}  "
                    f"{row['candidate_add']:>8}  {row['candidate_change']:>8}  {row['review']:>8}"
                )

            self.stdout.write('')
            self.stdout.write('CANDIDATE CHANGE FIELD DIAGNOSTIC')
            self.stdout.write('Carrier      Zone   Subzone   Area  Sub+Area')
            self.stdout.write('--------  -------  --------  -----  --------')
            for row in summary.get('carrier_summary', []):
                if row.get('candidate_change', 0):
                    self.stdout.write(
                        f"{row['carrier']:<8}  {row.get('change_zone', 0):>7}  {row.get('change_subzone_only', 0):>8}  "
                        f"{row.get('change_area_only', 0):>5}  {row.get('change_subzone_and_area', 0):>8}"
                    )

            self.stdout.write('')
            self.stdout.write('CURRENT DJANGO COVERAGE DIAGNOSTIC')
            self.stdout.write('Carrier   Current  DetailDiff  LocationAbsent')
            self.stdout.write('--------  -------  ----------  --------------')
            for row in summary.get('carrier_summary', []):
                self.stdout.write(
                    f"{row['carrier']:<8}  {row.get('current_rows', 0):>7}  "
                    f"{row.get('current_detail_diff', 0):>10}  {row.get('current_location_absent', 0):>14}"
                )

            samples = summary.get('change_samples', [])
            if samples:
                self.stdout.write('')
                self.stdout.write('REPRESENTATIVE CANDIDATE_CHANGE SAMPLES')
                for row in samples[:30]:
                    current = '; '.join(
                        f"{item.get('zone','')}/{item.get('subzone','') or '-'}/{item.get('area','') or '-'}"
                        for item in row.get('current_values', [])
                    ) or '-'
                    source = f"{row.get('source_zone','')}/{row.get('source_subzone','') or '-'}/{row.get('source_area','') or '-'}"
                    self.stdout.write(
                        f"{row.get('carrier','')} {row.get('service','')} | {row.get('suburb','')} {row.get('state','')} {row.get('postcode','')} "
                        f"| {row.get('change_kind','')} | CURRENT {current} -> SOURCE {source}"
                    )

            preview = summary.get('delta_preview', [])
            if preview:
                self.stdout.write('')
                self.stdout.write('FIRST DELTA / REVIEW ROWS')
                self.stdout.write('Carrier  Service  Suburb                     St   PC     Zone      Decision')
                self.stdout.write('-------  -------  -------------------------  ---  -----  --------  ---------------------------')
                for row in preview[:50]:
                    self.stdout.write(
                        f"{row.get('carrier',''):<7}  {row.get('service','-'):<7}  "
                        f"{row.get('suburb','')[:25]:<25}  {row.get('state',''):<3}  "
                        f"{row.get('postcode',''):<5}  {row.get('zone','')[:8]:<8}  {row.get('decision','')}"
                    )

            for warning in summary.get('warnings', []):
                self.stdout.write(f'WARNING: {warning}')

            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('VALIDATION ONLY. NO FREIGHT ZONES WERE ADDED, UPDATED OR DELETED.'))
            self.stdout.write('PHASE 3 HAS NO ZONES ACTIVATION COMMAND. This diagnostic separates zone/subzone/area differences before any activation is designed.')
        except ZonesImportError as exc:
            raise CommandError(str(exc)) from exc

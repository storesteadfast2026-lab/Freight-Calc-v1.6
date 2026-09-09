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
            self.stdout.write(f"Exact current FreightZone matches: {summary['exact_matches']}")
            self.stdout.write(f"Candidate additions: {summary['candidate_add']}")
            self.stdout.write(f"Candidate changes: {summary['candidate_change']}")
            self.stdout.write(f"Rows requiring review: {summary['review_total']}")
            self.stdout.write(f"Current relevant rows not safely represented by source: {summary['current_relevant_not_in_source']}")

            self.stdout.write('')
            self.stdout.write('CARRIER -> SERVICE MAPPING')
            self.stdout.write('Carrier   Service    Basis')
            self.stdout.write('--------  ---------  ------------------------------------------------')
            for row in summary.get('service_mapping_preview', []):
                self.stdout.write(f"{row['carrier']:<8}  {row['service']:<9}  {row['basis']}")
                if row.get('ambiguous'):
                    self.stdout.write(
                        f"          configured={','.join(row['configured_services']) or '-'}; "
                        f"zone-enabled={','.join(row['zone_enabled_services']) or '-'}; "
                        f"existing-zones={','.join(row['existing_zone_services']) or '-'}"
                    )

            self.stdout.write('')
            self.stdout.write('RELEVANT CARRIER DELTA SUMMARY')
            self.stdout.write('Carrier   Source     Exact      Add     Change    Review')
            self.stdout.write('--------  --------  --------  --------  --------  --------')
            for row in summary.get('carrier_summary', []):
                self.stdout.write(
                    f"{row['carrier']:<8}  {row['source_rows']:>8}  {row['exact']:>8}  "
                    f"{row['candidate_add']:>8}  {row['candidate_change']:>8}  {row['review']:>8}"
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
            self.stdout.write('PHASE 1 HAS NO ZONES ACTIVATION COMMAND. Review service mapping and deltas first.')
        except ZonesImportError as exc:
            raise CommandError(str(exc)) from exc

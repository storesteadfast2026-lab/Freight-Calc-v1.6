from django.core.management.base import BaseCommand, CommandError

from apps.clients.models import Client
from apps.imports.services.postcodes import (
    POSTCODES_ACTIVATION_POLICY,
    POSTCODES_POLICY_VERSION,
    PostcodesImportError,
    snapshot_ftp_postcodes_file,
    uploaded_data_root,
    validate_postcodes_file,
)


class Command(BaseCommand):
    help = (
        'Snapshot and validate uploaded_data/postcodes.csv using the ADD-ONLY policy. '
        'Validation never changes the operational Suburb table.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--client', default='STH', help='Owning client code. Default: STH')
        parser.add_argument('--filename', default='postcodes.csv', help='Filename inside uploaded_data.')

    def _write_table(self, headers, rows):
        rows = [[str(value) for value in row] for row in rows]
        widths = [len(str(header)) for header in headers]
        for row in rows:
            for index, value in enumerate(row):
                widths[index] = max(widths[index], len(value))

        def render(row):
            return '  '.join(value.ljust(widths[index]) for index, value in enumerate(row))

        self.stdout.write(render([str(header) for header in headers]))
        self.stdout.write(render(['-' * width for width in widths]))
        for row in rows:
            self.stdout.write(render(row))

    def _write_summary(self, external_file, summary):
        self.stdout.write(self.style.SUCCESS(f'FTP postcodes file #{external_file.pk} validated.'))
        self.stdout.write(f'Source format: {summary.get("source_format")}')
        self.stdout.write(f'Policy version: {summary.get("policy_version")}')
        self.stdout.write(f'Activation policy: {summary.get("activation_policy")}')
        self.stdout.write(f'Rows read: {summary.get("rows_read", 0)}')
        self.stdout.write(f'Valid Australian rows: {summary.get("candidate_rows", 0)}')
        self.stdout.write(f'Excluded source rows: {summary.get("excluded_rows_count", 0)}')
        self.stdout.write(
            'Existing master rows confirmed in current source: '
            f'{summary.get("existing_confirmed_in_current_source", 0)}'
        )
        self.stdout.write(f'NEW rows eligible for ADD: {summary.get("new_rows_to_add", 0)}')
        self.stdout.write(
            'Existing master rows not in current source: '
            f'{summary.get("existing_not_in_current_source_preserved", 0)} -> PRESERVE EXISTING'
        )
        self.stdout.write(f'Existing master origin: {summary.get("existing_master_origin", "-")}')
        self.stdout.write(
            'Suburb/state groups with multiple postcodes: '
            f'{summary.get("multi_postcode_suburb_state_groups", 0)} (allowed)'
        )

        excluded = summary.get('excluded_rows') or []
        if excluded:
            self.stdout.write('')
            self.stdout.write('EXCLUDED SOURCE ROWS')
            self._write_table(
                ('Row', 'Suburb', 'State', 'Postcode', 'Reason'),
                [
                    (
                        row.get('source_row', ''),
                        row.get('suburb', ''),
                        row.get('state', ''),
                        row.get('postcode', ''),
                        row.get('reason', ''),
                    )
                    for row in excluded
                ],
            )

        new_rows = summary.get('new_rows_preview') or []
        if new_rows:
            self.stdout.write('')
            self.stdout.write('NEW FROM FTP POSTCODES - ADD PREVIEW')
            self._write_table(
                ('Suburb', 'State', 'Postcode', 'Action', 'Possible alias', 'Existing other postcode(s)'),
                [
                    (
                        row.get('suburb', ''),
                        row.get('state', ''),
                        row.get('postcode', ''),
                        row.get('action', ''),
                        row.get('possible_alias') or '-',
                        ','.join(row.get('existing_same_suburb_state_postcodes') or []) or '-',
                    )
                    for row in new_rows
                ],
            )
            self.stdout.write('')
            self.stdout.write(
                'NOTE: alias/spelling information is diagnostic only. It does not block ADD and does not rename source data.'
            )

        preserved = summary.get('preserved_existing_preview') or []
        if preserved:
            self.stdout.write('')
            self.stdout.write('EXISTING MASTER NOT IN CURRENT SOURCE - PREVIEW')
            self._write_table(
                ('Suburb', 'State', 'Postcode', 'Action'),
                [
                    (row['suburb'], row['state'], row['postcode'], row['action'])
                    for row in preserved
                ],
            )
            if summary.get('existing_not_in_current_source_preserved', 0) > len(preserved):
                self.stdout.write(
                    f'... {summary["existing_not_in_current_source_preserved"] - len(preserved)} more row(s) not shown.'
                )

        for warning in summary.get('warnings', []):
            self.stdout.write(self.style.WARNING(f'WARNING: {warning}'))

        self.stdout.write('')
        self.stdout.write(self.style.WARNING('VALIDATION ONLY. THE SUBURB MASTER WAS NOT CHANGED.'))
        self.stdout.write(
            self.style.WARNING(
                'ADD-ONLY POLICY: existing rows are never updated, renamed or deleted. '
                'Only NEW source triplets are eligible for explicit activation.'
            )
        )

    def handle(self, *args, **options):
        client_code = str(options['client']).strip().upper()
        filename = str(options['filename']).strip()
        try:
            client = Client.objects.get(code=client_code)
        except Client.DoesNotExist as exc:
            raise CommandError(f'Client {client_code!r} does not exist.') from exc

        self.stdout.write(f'FTP folder: {uploaded_data_root()}')
        self.stdout.write(f'Postcodes source: {filename}')
        self.stdout.write(f'File owner: {client.code}')
        self.stdout.write('Operational scope: global Australian Suburb lookup')

        try:
            external_file, created = snapshot_ftp_postcodes_file(
                client=client,
                filename=filename,
            )
            if not created:
                self.stdout.write(
                    self.style.WARNING(
                        f'No new snapshot created. Identical content is already file '
                        f'#{external_file.pk} with status {external_file.status}.'
                    )
                )
                summary = external_file.validation_summary or {}
                if (
                    external_file.status in {'VALIDATED', 'ACTIVE', 'ROLLED_BACK', 'ARCHIVED'}
                    and summary.get('source_format') == 'FTP_POSTCODES'
                    and summary.get('policy_version') == POSTCODES_POLICY_VERSION
                    and summary.get('activation_policy') == POSTCODES_ACTIVATION_POLICY
                ):
                    self.stdout.write('Reusing the existing ADD-ONLY validation summary for review.')
                    self._write_summary(external_file, summary)
                    return
                if summary.get('source_format') == 'FTP_POSTCODES':
                    self.stdout.write('Existing summary predates the current ADD-ONLY Postcodes policy.')
                self.stdout.write('Re-validating the existing snapshot with the current policy.')

            summary = validate_postcodes_file(external_file)
        except PostcodesImportError as exc:
            raise CommandError(str(exc)) from exc

        self._write_summary(external_file, summary)

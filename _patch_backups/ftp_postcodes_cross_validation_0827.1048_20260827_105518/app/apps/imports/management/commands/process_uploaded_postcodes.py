from django.core.management.base import BaseCommand, CommandError

from apps.clients.models import Client
from apps.imports.services.postcodes import (
    PostcodesImportError,
    snapshot_ftp_postcodes_file,
    uploaded_data_root,
    validate_postcodes_file,
)


class Command(BaseCommand):
    help = (
        'Snapshot and validate uploaded_data/postcodes.csv. '
        'Phase 1 is validation-only and never changes the operational Suburb table.'
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
        self.stdout.write(f'Rows read: {summary.get("rows_read", 0)}')
        self.stdout.write(f'Australian candidate rows: {summary.get("candidate_rows", 0)}')
        self.stdout.write(f'Excluded source rows: {summary.get("excluded_rows_count", 0)}')
        self.stdout.write(f'Already present in Django: {summary.get("existing_matches", 0)}')
        self.stdout.write(f'Rows that would be added: {summary.get("would_add", 0)}')
        self.stdout.write(f'Current Django rows not in source: {summary.get("current_not_in_source", 0)}')
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

        would_add = summary.get('would_add_preview') or []
        if would_add:
            self.stdout.write('')
            self.stdout.write('WOULD ADD TO DJANGO - PREVIEW')
            self._write_table(
                ('Suburb', 'State', 'Postcode'),
                [(row['suburb'], row['state'], row['postcode']) for row in would_add],
            )
            if summary.get('would_add', 0) > len(would_add):
                self.stdout.write(
                    f'... {summary["would_add"] - len(would_add)} more row(s) not shown.'
                )

        missing = summary.get('current_not_in_source_preview') or []
        if missing:
            self.stdout.write('')
            self.stdout.write('CURRENT DJANGO ROWS NOT IN SOURCE - PREVIEW')
            self._write_table(
                ('Suburb', 'State', 'Postcode', 'Phase 1 action'),
                [
                    (row['suburb'], row['state'], row['postcode'], 'PRESERVE EXISTING')
                    for row in missing
                ],
            )
            if summary.get('current_not_in_source', 0) > len(missing):
                self.stdout.write(
                    f'... {summary["current_not_in_source"] - len(missing)} more row(s) not shown.'
                )

        for warning in summary.get('warnings', []):
            self.stdout.write(self.style.WARNING(f'WARNING: {warning}'))

        self.stdout.write('')
        self.stdout.write(
            self.style.WARNING(
                'VALIDATION ONLY. NO SUBURBS OR POSTCODES WERE ADDED, UPDATED OR DELETED.'
            )
        )
        self.stdout.write(
            self.style.WARNING(
                'PHASE 1 HAS NO ACTIVATION COMMAND. Review this delta before activation is implemented.'
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
                if external_file.status in {'VALIDATED', 'ACTIVE', 'ROLLED_BACK', 'ARCHIVED'}:
                    summary = external_file.validation_summary or {}
                    if summary.get('source_format') == 'FTP_POSTCODES':
                        self.stdout.write('Reusing the existing validation summary for review.')
                        self._write_summary(external_file, summary)
                        return
                self.stdout.write('Re-validating the existing snapshot.')

            summary = validate_postcodes_file(external_file)
        except PostcodesImportError as exc:
            raise CommandError(str(exc)) from exc

        self._write_summary(external_file, summary)

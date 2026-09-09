from django.core.management.base import BaseCommand, CommandError

from apps.clients.models import Client
from apps.imports.services.postcodes import (
    PostcodesImportError,
    activate_postcodes_file,
    snapshot_ftp_postcodes_file,
)


class Command(BaseCommand):
    help = (
        'Explicitly activate a VALIDATED FTP postcodes snapshot using ADD ONLY. '
        'Existing Suburb rows are never updated, renamed or deleted.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--client', default='STH', help='Owning client code. Default: STH')
        parser.add_argument('--filename', default='postcodes.csv', help='Filename inside uploaded_data.')

    def handle(self, *args, **options):
        client_code = str(options['client']).strip().upper()
        filename = str(options['filename']).strip()
        try:
            client = Client.objects.get(code=client_code)
        except Client.DoesNotExist as exc:
            raise CommandError(f'Client {client_code!r} does not exist.') from exc

        try:
            external_file, created = snapshot_ftp_postcodes_file(
                client=client,
                filename=filename,
            )
            if created:
                raise PostcodesImportError(
                    f'New snapshot #{external_file.pk} was created. Run process_uploaded_postcodes first and review validation before activation.'
                )
            summary = activate_postcodes_file(external_file)
        except PostcodesImportError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f'Postcodes file #{external_file.pk} activated with ADD-ONLY policy.'))
        self.stdout.write(f'Created from FTP source: {summary.get("created_count", 0)}')
        self.stdout.write(
            f'Existing confirmed in current source: {summary.get("existing_confirmed_in_current_source", 0)}'
        )
        self.stdout.write(
            'Existing not in current source preserved: '
            f'{summary.get("existing_not_in_current_source_preserved", 0)}'
        )
        self.stdout.write('Updated existing rows: 0')
        self.stdout.write('Deleted existing rows: 0')
        self.stdout.write('Renamed existing rows: 0')
        created_rows = summary.get('created_rows') or []
        if created_rows:
            self.stdout.write('')
            self.stdout.write('CREATED ROWS')
            for row in created_rows:
                self.stdout.write(
                    f'- {row.get("suburb")} {row.get("state")} {row.get("postcode")} '
                    f'(origin={row.get("origin")})'
                )

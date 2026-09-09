from django.core.management.base import BaseCommand, CommandError

from apps.clients.models import Client
from apps.imports.services.fuel import FuelImportError, validate_fuel_file
from apps.imports.services.uploaded_data import snapshot_ftp_fuel_file, uploaded_data_root


class Command(BaseCommand):
    help = (
        'Snapshot and validate the FTP uploaded_data/fuel.csv file. '
        'This command never activates Fuel rates.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--client', default='STH', help='Client code. Default: STH')
        parser.add_argument('--filename', default='fuel.csv', help='Filename inside uploaded_data.')

    def handle(self, *args, **options):
        client_code = str(options['client']).strip().upper()
        filename = str(options['filename']).strip()
        try:
            client = Client.objects.get(code=client_code)
        except Client.DoesNotExist as exc:
            raise CommandError(f'Client {client_code!r} does not exist.') from exc

        self.stdout.write(f'FTP folder: {uploaded_data_root()}')
        self.stdout.write(f'Fuel source: {filename}')
        self.stdout.write(f'Client: {client.code}')

        try:
            external_file, created = snapshot_ftp_fuel_file(
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
                    self.stdout.write('NO FUEL RATES WERE ACTIVATED.')
                    return
                self.stdout.write('Re-validating the existing snapshot because it is not in a validated lifecycle state.')

            summary = validate_fuel_file(external_file)
        except FuelImportError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f'FTP Fuel file #{external_file.pk} validated.'))
        self.stdout.write(f'Source format: {summary.get("source_format")}')
        self.stdout.write(f'Rows valid: {summary.get("rows_valid", 0)}')
        self.stdout.write(f'Client configs matched: {summary.get("configs_matched", 0)}')
        self.stdout.write(f'Configs that would change: {summary.get("configs_to_update", 0)}')
        self.stdout.write(f'Configs unchanged: {summary.get("configs_unchanged", 0)}')
        if summary.get('ratecards_not_found_in_django'):
            self.stdout.write(
                self.style.WARNING(
                    'Source rate cards not used by this client: '
                    + ', '.join(summary['ratecards_not_found_in_django'])
                )
            )
        if summary.get('django_ratecards_missing_from_file'):
            self.stdout.write(
                self.style.WARNING(
                    'Client rate cards missing from source: '
                    + ', '.join(summary['django_ratecards_missing_from_file'])
                )
            )
        for warning in summary.get('warnings', []):
            self.stdout.write(self.style.WARNING(f'WARNING: {warning}'))
        self.stdout.write(self.style.WARNING('VALIDATION ONLY. NO FUEL RATES WERE ACTIVATED.'))

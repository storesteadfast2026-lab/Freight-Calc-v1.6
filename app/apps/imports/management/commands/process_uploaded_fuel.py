from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from apps.carriers.models import ClientCarrierConfig
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

    @staticmethod
    def _percent(value) -> str:
        if value in (None, ''):
            return '-'
        try:
            percent = Decimal(str(value)) * Decimal('100')
        except (InvalidOperation, ValueError, TypeError):
            return str(value)
        return f'{percent:.2f}%'

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
        self.stdout.write(self.style.SUCCESS(f'FTP Fuel file #{external_file.pk} validated.'))
        self.stdout.write(f'Source format: {summary.get("source_format")}')
        self.stdout.write(f'Rows valid: {summary.get("rows_valid", 0)}')
        self.stdout.write(f'Client configs matched: {summary.get("configs_matched", 0)}')
        self.stdout.write(f'Configs that would change: {summary.get("configs_to_update", 0)}')
        self.stdout.write(f'Configs unchanged: {summary.get("configs_unchanged", 0)}')

        preview = summary.get('preview') or []
        if preview:
            self.stdout.write('')
            self.stdout.write('MATCHED CLIENT CONFIGURATIONS')
            self._write_table(
                ('Carrier', 'Service', 'Rate card', 'Current Fuel', 'New Fuel', 'Result'),
                [
                    (
                        row.get('carrier', ''),
                        row.get('service', ''),
                        row.get('ratecard', ''),
                        self._percent(row.get('current_rate')),
                        self._percent(row.get('new_rate')),
                        row.get('result', ''),
                    )
                    for row in preview
                ],
            )

        unmatched = summary.get('unmatched_client_configs') or []
        if unmatched:
            config_ids = [row.get('config_id') for row in unmatched if row.get('config_id')]
            current_rates = {
                config.pk: config.fuel_levy
                for config in ClientCarrierConfig.objects.filter(pk__in=config_ids)
            }
            self.stdout.write('')
            self.stdout.write('CLIENT CONFIGURATIONS MISSING FROM SOURCE')
            self._write_table(
                ('Carrier', 'Service', 'Rate card', 'Current Fuel', 'Action'),
                [
                    (
                        row.get('carrier', ''),
                        row.get('service', ''),
                        row.get('ratecard', ''),
                        self._percent(current_rates.get(row.get('config_id'))),
                        'PRESERVE EXISTING',
                    )
                    for row in unmatched
                ],
            )

        if summary.get('ratecards_not_found_in_django'):
            self.stdout.write('')
            self.stdout.write(
                self.style.WARNING(
                    'SOURCE RATE CARDS NOT USED BY THIS CLIENT: '
                    + ', '.join(summary['ratecards_not_found_in_django'])
                )
            )

        for warning in summary.get('warnings', []):
            self.stdout.write(self.style.WARNING(f'WARNING: {warning}'))

        self.stdout.write('')
        self.stdout.write(self.style.WARNING('VALIDATION ONLY. NO FUEL RATES WERE ACTIVATED.'))

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
                    summary = external_file.validation_summary or {}
                    if summary.get('preview') is not None and summary.get('source_format'):
                        self.stdout.write('Reusing the existing validation summary for review.')
                        self._write_summary(external_file, summary)
                        return
                    self.stdout.write(
                        'Existing snapshot has no reusable validation summary; validating it again.'
                    )
                else:
                    self.stdout.write(
                        'Re-validating the existing snapshot because it is not in a validated lifecycle state.'
                    )

            summary = validate_fuel_file(external_file)
        except FuelImportError as exc:
            raise CommandError(str(exc)) from exc

        self._write_summary(external_file, summary)

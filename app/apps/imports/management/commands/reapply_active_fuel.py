from django.core.management.base import BaseCommand, CommandError

from apps.clients.models import Client
from apps.imports.services.fuel import FuelImportError, reapply_active_fuel_rates


class Command(BaseCommand):
    help = 'Reapply the active Admin fuel dataset to ClientCarrierConfig records.'

    def add_arguments(self, parser):
        parser.add_argument('--client', default='STH')

    def handle(self, *args, **options):
        client = Client.objects.filter(code=options['client'].strip().upper()).first()
        if client is None:
            raise CommandError(f'Client not found: {options["client"]}')
        try:
            summary = reapply_active_fuel_rates(client)
        except FuelImportError as exc:
            raise CommandError(str(exc)) from exc
        if summary['active_fuel_file_id'] is None:
            self.stdout.write(self.style.WARNING('No active Admin fuel dataset found.'))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Reapplied fuel file #{summary['active_fuel_file_id']} to "
                f"{summary['configs_reapplied']} carrier configs."
            )
        )

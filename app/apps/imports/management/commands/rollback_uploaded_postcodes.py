from django.core.management.base import BaseCommand, CommandError

from apps.imports.models import ExternalDataFile
from apps.imports.services.postcodes import PostcodesImportError, rollback_postcodes_file


class Command(BaseCommand):
    help = (
        'Rollback the ACTIVE Postcodes file by removing only rows created by that activation. '
        'Historical/pre-existing rows are never deleted.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--file-id', required=True, type=int, help='ACTIVE SUBURBS ExternalDataFile id.')
        parser.add_argument('--reason', required=True, help='Required rollback reason.')

    def handle(self, *args, **options):
        try:
            external_file = ExternalDataFile.objects.get(
                pk=options['file_id'],
                file_type='SUBURBS',
            )
        except ExternalDataFile.DoesNotExist as exc:
            raise CommandError('SUBURBS ExternalDataFile not found.') from exc

        try:
            summary = rollback_postcodes_file(
                external_file,
                reason=str(options['reason']).strip(),
            )
        except PostcodesImportError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.WARNING(f'Postcodes file #{external_file.pk} rolled back.'))
        self.stdout.write(f'Created rows removed: {summary.get("created_rows_removed", 0)}')
        self.stdout.write(f'Created rows already missing: {summary.get("created_rows_already_missing", 0)}')
        self.stdout.write('Historical rows modified: 0')
        self.stdout.write('Historical rows deleted: 0')
        self.stdout.write(f'Reason: {summary.get("reason")}')

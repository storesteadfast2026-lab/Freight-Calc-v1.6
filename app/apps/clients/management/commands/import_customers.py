"""Technical Customer import; operational users import through Django Admin."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.clients.customer_import import CustomerImportError, import_customers, preview_customers


class Command(BaseCommand):
    help = 'Validate or import a Translogic customers.xls using the Admin importer.'

    def add_arguments(self, parser):
        parser.add_argument('path', type=Path)
        parser.add_argument('--apply', action='store_true', help='Confirm the import after validation.')

    def handle(self, *args, **options):
        path = options['path']
        try:
            content = path.read_bytes()
            preview = preview_customers(content)
            self.stdout.write(
                f'Rows {preview.total_rows}; new {len(preview.new)}; changed {len(preview.changed)}; '
                f'unchanged {len(preview.unchanged)}; missing {len(preview.missing)}; '
                f'invalid {len(preview.errors)}; duplicates {len(preview.duplicates)}; '
                f'special {len(preview.special)}.'
            )
            if preview.errors or preview.duplicates:
                raise CommandError('\n'.join((preview.errors + preview.duplicates)[:25]))
            if options['apply']:
                history = import_customers(content, filename=path.name)
                self.stdout.write(self.style.SUCCESS(f'Imported Customer master; history #{history.pk}.'))
            else:
                self.stdout.write('Validation only. Use --apply to import.')
        except (OSError, CustomerImportError) as exc:
            raise CommandError(str(exc)) from exc

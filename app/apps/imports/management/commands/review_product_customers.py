from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Retired: CUSTOMER now resolves the owning Client during source validation.'

    def handle(self, *args, **options):
        raise CommandError(
            'This command is retired. CUSTOMER identifies Client; it must not be assigned '
            'as a second field on Product. Create Clients explicitly and validate a new source.'
        )

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.authentication_gateway.services import DJANGO_ADMINISTRATOR_GROUP


STANDARD_PERMISSION_TARGETS = {
    'clients': {
        'client': {'view', 'add', 'change'},
        'freightcalculator': {'view', 'add', 'change'},
    },
    'locations': {
        'fromaddress': {'view', 'add', 'change'},
        'suburb': {'view', 'add', 'change'},
    },
    'products': {
        'product': {'view', 'add', 'change'},
        'productkitcomponent': {'view', 'add', 'change'},
    },
    'carriers': {
        'carrier': {'view', 'add', 'change'},
        'carrierservice': {'view', 'add', 'change'},
        'clientcarrierconfig': {'view', 'add', 'change'},
    },
    'rates': {
        'freightzone': {'view', 'add', 'change'},
        'freightrate': {'view', 'add', 'change'},
        'carriertailgatecharge': {'view', 'add', 'change'},
    },
    'imports': {
        'externaldatafile': {
            'view', 'add', 'change',
            'validate_external_data_file',
            'activate_fuel',
            'rollback_fuel',
            'download_external_data_file',
        },
        'productsourcerow': {'view'},
        'stocksourcerow': {'view'},
    },
    'audit': {
        'auditevent': {'view'},
    },
}


class Command(BaseCommand):
    help = 'Create or update the minimum Django Administrator group and permissions.'

    @transaction.atomic
    def handle(self, *args, **options):
        group, created = Group.objects.get_or_create(name=DJANGO_ADMINISTRATOR_GROUP)
        permissions = []
        missing = []

        for app_label, models in STANDARD_PERMISSION_TARGETS.items():
            for model_name, actions in models.items():
                for action in actions:
                    codename = (
                        f'{action}_{model_name}'
                        if action in {'view', 'add', 'change', 'delete'}
                        else action
                    )
                    permission = Permission.objects.filter(
                        content_type__app_label=app_label,
                        content_type__model=model_name,
                        codename=codename,
                    ).first()
                    if permission is None:
                        missing.append(f'{app_label}.{codename}')
                    else:
                        permissions.append(permission)

        if missing:
            raise CommandError(
                'Missing permissions. Run migrations first, then retry: '
                + ', '.join(sorted(missing))
            )

        group.permissions.set(permissions)
        action = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(
            f'{action} group "{DJANGO_ADMINISTRATOR_GROUP}" with '
            f'{len(permissions)} permissions.'
        ))
        self.stdout.write(
            'User/group administration and superuser assignment remain '
            'Technical-Superuser-only.'
        )

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.authentication_gateway.services import (
    ADMINISTRATORS_GROUP,
    CUSTOMERS_GROUP,
    LEGACY_DJANGO_ADMINISTRATOR_GROUP,
    STEADFAST_USERS_GROUP,
)


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
    help = 'Create or update the protected group-based access model.'

    @transaction.atomic
    def handle(self, *args, **options):
        legacy_group = Group.objects.filter(
            name=LEGACY_DJANGO_ADMINISTRATOR_GROUP
        ).first()
        administrators = Group.objects.filter(name=ADMINISTRATORS_GROUP).first()
        renamed_legacy = False

        if legacy_group is not None and administrators is None:
            legacy_group.name = ADMINISTRATORS_GROUP
            legacy_group.save(update_fields=['name'])
            administrators = legacy_group
            renamed_legacy = True
        elif administrators is None:
            administrators = Group.objects.create(name=ADMINISTRATORS_GROUP)
        elif legacy_group is not None:
            for user in legacy_group.user_set.all():
                user.groups.add(administrators)

        customers, customers_created = Group.objects.get_or_create(
            name=CUSTOMERS_GROUP
        )
        steadfast_users, steadfast_created = Group.objects.get_or_create(
            name=STEADFAST_USERS_GROUP
        )

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

        administrators.permissions.set(permissions)
        customers.permissions.clear()
        steadfast_users.permissions.clear()

        if renamed_legacy:
            action = 'Renamed legacy group to'
        else:
            action = 'Created or updated'
        self.stdout.write(self.style.SUCCESS(
            f'{action} group "{ADMINISTRATORS_GROUP}" with '
            f'{len(permissions)} permissions.'
        ))
        self.stdout.write(
            f'{"Created" if customers_created else "Updated"} group '
            f'"{CUSTOMERS_GROUP}" with 0 Django Admin permissions.'
        )
        self.stdout.write(
            f'{"Created" if steadfast_created else "Updated"} group '
            f'"{STEADFAST_USERS_GROUP}" with 0 Django Admin permissions.'
        )

        if legacy_group is not None and not renamed_legacy:
            self.stdout.write(self.style.WARNING(
                f'Legacy group "{LEGACY_DJANGO_ADMINISTRATOR_GROUP}" still exists '
                f'because "{ADMINISTRATORS_GROUP}" already existed. Review and '
                'transfer its users manually before deleting it.'
            ))

        direct_permission_users = list(
            get_user_model().objects
            .filter(is_superuser=False, user_permissions__isnull=False)
            .distinct()
            .values_list('username', flat=True)
        )
        if direct_permission_users:
            self.stdout.write(self.style.WARNING(
                'Individual permissions still exist for: '
                + ', '.join(direct_permission_users)
                + '. Review them before clearing; this command did not remove them.'
            ))

        self.stdout.write(
            'User/group administration and Super User assignment remain '
            'Super-User-only.'
        )

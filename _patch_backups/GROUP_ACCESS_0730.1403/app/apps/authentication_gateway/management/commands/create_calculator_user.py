from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.services import DJANGO_ADMINISTRATOR_GROUP
from apps.clients.models import Client


class Command(BaseCommand):
    help = 'Create a Customer User, Internal User, or minimum Django Administrator.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument(
            '--role',
            required=True,
            choices=['customer', 'internal'],
        )
        parser.add_argument('--client', help='Single client code for Customer User.')
        parser.add_argument(
            '--allowed-client',
            action='append',
            dest='allowed_clients',
            default=[],
            help='Allowed client code for selected-client Internal User. Repeat as needed.',
        )
        parser.add_argument(
            '--all-clients',
            action='store_true',
            help='Give an Internal User access to all active clients.',
        )
        parser.add_argument(
            '--django-admin',
            action='store_true',
            help='Create a normal Django Administrator. Requires internal + all clients.',
        )
        parser.add_argument('--first-name', default='')
        parser.add_argument('--last-name', default='')
        parser.add_argument(
            '--set-password',
            action='store_true',
            help='Prompt securely for an initial password. Otherwise password is unusable.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError(f'Invalid email address: {email}') from exc

        User = get_user_model()
        if User.objects.filter(username__iexact=email).exists():
            raise CommandError(f'A user with username/email {email} already exists.')
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(f'A user with email {email} already exists.')

        role_arg = options['role']
        client_code = (options.get('client') or '').strip()
        allowed_codes = [code.strip() for code in options['allowed_clients'] if code.strip()]
        all_clients = options['all_clients']
        django_admin = options['django_admin']

        if role_arg == 'customer':
            if not client_code:
                raise CommandError('Customer User requires --client CLIENT_CODE.')
            if allowed_codes or all_clients or django_admin:
                raise CommandError(
                    'Customer User cannot use --allowed-client, --all-clients or --django-admin.'
                )
            client = Client.objects.filter(code__iexact=client_code, active=True).first()
            if client is None:
                raise CommandError(f'Active client not found: {client_code}')
            profile_role = CalculatorUserProfile.Role.CUSTOMER_USER
            scope = CalculatorUserProfile.ClientScope.SINGLE_CLIENT
            selected_clients = []
        else:
            if client_code:
                raise CommandError('Internal User must not use --client.')
            if all_clients and allowed_codes:
                raise CommandError('Choose --all-clients or --allowed-client, not both.')
            if not all_clients and not allowed_codes:
                raise CommandError(
                    'Internal User requires --all-clients or at least one --allowed-client.'
                )
            if django_admin and not all_clients:
                raise CommandError('Django Administrator requires --all-clients.')

            client = None
            profile_role = CalculatorUserProfile.Role.INTERNAL_USER
            scope = (
                CalculatorUserProfile.ClientScope.ALL_CLIENTS
                if all_clients
                else CalculatorUserProfile.ClientScope.SELECTED_CLIENTS
            )
            selected_clients = []
            for code in allowed_codes:
                selected = Client.objects.filter(code__iexact=code, active=True).first()
                if selected and selected not in selected_clients:
                    selected_clients.append(selected)
            selected_clients.sort(key=lambda item: item.code)
            found_codes = {item.code.casefold() for item in selected_clients}
            missing_codes = [code for code in allowed_codes if code.casefold() not in found_codes]
            if missing_codes:
                raise CommandError(
                    'Active client(s) not found: ' + ', '.join(sorted(missing_codes))
                )

        user = User(
            username=email,
            email=email,
            first_name=options['first_name'].strip(),
            last_name=options['last_name'].strip(),
            is_active=True,
            is_staff=django_admin,
            is_superuser=False,
        )

        if options['set_password']:
            password = getpass('Initial password: ')
            confirmation = getpass('Confirm password: ')
            if not password:
                raise CommandError('Password cannot be empty.')
            if password != confirmation:
                raise CommandError('Passwords do not match.')
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.full_clean()
        user.save()

        profile = CalculatorUserProfile(
            user=user,
            role=profile_role,
            client_scope=scope,
            client=client,
            calculator_access=True,
        )
        profile.full_clean()
        profile.save()
        if selected_clients:
            profile.allowed_clients.set(selected_clients)

        if django_admin:
            group = Group.objects.filter(name=DJANGO_ADMINISTRATOR_GROUP).first()
            if group is None:
                raise CommandError(
                    f'Group "{DJANGO_ADMINISTRATOR_GROUP}" does not exist. '
                    'Run setup_access_roles first.'
                )
            user.groups.add(group)

        self.stdout.write(self.style.SUCCESS(
            f'Created {profile.get_role_display()}: {email}'
        ))
        self.stdout.write(f'Client scope: {profile.get_client_scope_display()}')
        if django_admin:
            self.stdout.write('Django Admin: enabled as non-superuser administrator.')
        if not options['set_password']:
            self.stdout.write(self.style.WARNING(
                'Password is unusable. Run changepassword or implement the invitation flow '
                'before this user can log in.'
            ))

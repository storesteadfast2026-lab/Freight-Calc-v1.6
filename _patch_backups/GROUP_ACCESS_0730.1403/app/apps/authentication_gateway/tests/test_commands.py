from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.services import DJANGO_ADMINISTRATOR_GROUP
from apps.clients.models import Client


class AccessManagementCommandTests(TestCase):
    def setUp(self):
        self.client_sth = Client.objects.create(code='STH', name='STH')

    def test_setup_access_roles_creates_minimum_group_without_user_management(self):
        output = StringIO()
        call_command('setup_access_roles', stdout=output)

        group = Group.objects.get(name=DJANGO_ADMINISTRATOR_GROUP)
        codenames = set(group.permissions.values_list('codename', flat=True))
        self.assertIn('view_client', codenames)
        self.assertIn('activate_fuel', codenames)
        self.assertIn('view_auditevent', codenames)
        self.assertNotIn('add_user', codenames)
        self.assertNotIn('change_group', codenames)

    def test_create_customer_user(self):
        output = StringIO()
        call_command(
            'create_calculator_user',
            email='CUSTOMER@EXAMPLE.COM',
            role='customer',
            client='STH',
            stdout=output,
        )

        user = get_user_model().objects.get(username='customer@example.com')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(
            user.calculator_profile.role,
            CalculatorUserProfile.Role.CUSTOMER_USER,
        )
        self.assertEqual(user.calculator_profile.client, self.client_sth)

    def test_create_minimum_django_administrator(self):
        call_command('setup_access_roles', stdout=StringIO())
        call_command(
            'create_calculator_user',
            email='admin@example.com',
            role='internal',
            all_clients=True,
            django_admin=True,
            stdout=StringIO(),
        )

        user = get_user_model().objects.get(username='admin@example.com')
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.groups.filter(name=DJANGO_ADMINISTRATOR_GROUP).exists())
        self.assertEqual(
            user.calculator_profile.client_scope,
            CalculatorUserProfile.ClientScope.ALL_CLIENTS,
        )

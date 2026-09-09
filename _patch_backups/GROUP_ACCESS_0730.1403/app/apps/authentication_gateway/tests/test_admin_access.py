from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.services import DJANGO_ADMINISTRATOR_GROUP
from apps.clients.models import Client


class DjangoAdminAccessMiddlewareTests(TestCase):
    def setUp(self):
        self.client_record = Client.objects.create(code='STH', name='STH')
        self.User = get_user_model()

    def _staff_user(self, email, scope):
        user = self.User.objects.create_user(
            username=email,
            email=email,
            password='test-pass',
            is_staff=True,
        )
        profile = CalculatorUserProfile.objects.create(
            user=user,
            role=CalculatorUserProfile.Role.INTERNAL_USER,
            client_scope=scope,
        )
        if scope == CalculatorUserProfile.ClientScope.SELECTED_CLIENTS:
            profile.allowed_clients.add(self.client_record)
        return user

    def test_staff_flag_alone_is_rejected(self):
        user = self._staff_user(
            'staff@example.com',
            CalculatorUserProfile.ClientScope.ALL_CLIENTS,
        )
        self.client.force_login(user)
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 403)

    def test_selected_client_staff_is_rejected_even_with_group(self):
        user = self._staff_user(
            'selected@example.com',
            CalculatorUserProfile.ClientScope.SELECTED_CLIENTS,
        )
        group = Group.objects.create(name=DJANGO_ADMINISTRATOR_GROUP)
        user.groups.add(group)
        self.client.force_login(user)
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 403)

    def test_approved_django_administrator_can_open_admin(self):
        call_command('setup_access_roles', stdout=StringIO())
        user = self._staff_user(
            'admin@example.com',
            CalculatorUserProfile.ClientScope.ALL_CLIENTS,
        )
        user.groups.add(Group.objects.get(name=DJANGO_ADMINISTRATOR_GROUP))
        self.client.force_login(user)
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(user.has_perm('imports.activate_fuel'))
        self.assertFalse(user.has_perm('auth.change_user'))

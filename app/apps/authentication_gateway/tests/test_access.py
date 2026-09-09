from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.services import (
    DJANGO_ADMINISTRATOR_GROUP,
    allowed_clients_for,
    is_django_administrator,
    resolve_authorized_client,
)
from apps.clients.models import Client


class CalculatorAccessServiceTests(TestCase):
    def setUp(self):
        self.client_sth = Client.objects.create(code='STH', name='STH')
        self.client_other = Client.objects.create(code='OTHER', name='Other')
        self.User = get_user_model()

    def _user(self, email):
        return self.User.objects.create_user(username=email, email=email, password='test-pass')

    def test_customer_user_is_limited_to_one_client(self):
        user = self._user('customer@example.com')
        CalculatorUserProfile.objects.create(
            user=user,
            role=CalculatorUserProfile.Role.CUSTOMER_USER,
            client_scope=CalculatorUserProfile.ClientScope.SINGLE_CLIENT,
            client=self.client_sth,
        )

        self.assertEqual(list(allowed_clients_for(user)), [self.client_sth])
        self.assertEqual(resolve_authorized_client(user).pk, self.client_sth.pk)
        with self.assertRaises(PermissionDenied):
            resolve_authorized_client(user, 'OTHER')

    def test_internal_selected_clients_are_enforced(self):
        user = self._user('internal@example.com')
        profile = CalculatorUserProfile.objects.create(
            user=user,
            role=CalculatorUserProfile.Role.INTERNAL_USER,
            client_scope=CalculatorUserProfile.ClientScope.SELECTED_CLIENTS,
        )
        profile.allowed_clients.add(self.client_other)

        self.assertEqual(list(allowed_clients_for(user)), [self.client_other])
        self.assertEqual(resolve_authorized_client(user, 'OTHER').pk, self.client_other.pk)
        with self.assertRaises(PermissionDenied):
            resolve_authorized_client(user, 'STH')

    def test_internal_all_clients_defaults_to_sth_when_available(self):
        user = self._user('all@example.com')
        CalculatorUserProfile.objects.create(
            user=user,
            role=CalculatorUserProfile.Role.INTERNAL_USER,
            client_scope=CalculatorUserProfile.ClientScope.ALL_CLIENTS,
        )

        self.assertEqual(resolve_authorized_client(user).pk, self.client_sth.pk)
        self.assertEqual(allowed_clients_for(user).count(), 2)

    def test_staff_user_needs_group_and_internal_all_clients(self):
        user = self._user('admin@example.com')
        user.is_staff = True
        user.save(update_fields=['is_staff'])
        CalculatorUserProfile.objects.create(
            user=user,
            role=CalculatorUserProfile.Role.INTERNAL_USER,
            client_scope=CalculatorUserProfile.ClientScope.ALL_CLIENTS,
        )

        self.assertFalse(is_django_administrator(user))
        group = Group.objects.create(name=DJANGO_ADMINISTRATOR_GROUP)
        user.groups.add(group)
        self.assertTrue(is_django_administrator(user))

    def test_user_without_profile_has_no_calculator_access(self):
        user = self._user('noprofile@example.com')
        with self.assertRaises(PermissionDenied):
            allowed_clients_for(user)

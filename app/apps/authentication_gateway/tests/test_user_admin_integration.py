from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.authentication_gateway.admin import STHUserAdmin
from apps.authentication_gateway.forms import (
    STHUserChangeForm,
    STHUserCreationForm,
)
from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.services import (
    ADMINISTRATORS_GROUP,
    CUSTOMERS_GROUP,
    STEADFAST_USERS_GROUP,
    configure_user_from_primary_group,
    primary_access_group_for,
)
from apps.clients.models import Client


class GroupBasedUserAdminTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.superuser = self.User.objects.create_superuser(
            username='super',
            email='super@example.com',
            password='test-password',
        )
        self.client.force_login(self.superuser)
        self.client_record = Client.objects.create(code='STH', name='STH')
        for group_name in (
            ADMINISTRATORS_GROUP,
            CUSTOMERS_GROUP,
            STEADFAST_USERS_GROUP,
        ):
            Group.objects.create(name=group_name)

    def test_builtin_user_admin_is_replaced_without_profile_inline(self):
        model_admin = admin.site._registry[self.User]
        self.assertIsInstance(model_admin, STHUserAdmin)
        self.assertEqual(model_admin.inlines, ())
        self.assertIs(model_admin.form, STHUserChangeForm)
        self.assertIs(model_admin.add_form, STHUserCreationForm)

    def test_user_change_page_uses_primary_group_and_hides_individual_permissions(self):
        user = self.User.objects.create_user(
            username='customer@example.com',
            password='test-password',
        )
        configure_user_from_primary_group(
            user,
            CUSTOMERS_GROUP,
            self.client_record,
        )

        response = self.client.get(
            reverse('admin:auth_user_change', args=[user.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Primary access group')
        self.assertContains(response, 'Customer client')
        self.assertContains(response, 'Individual permissions: disabled')
        self.assertNotContains(response, 'User permissions')
        self.assertNotContains(response, 'id_user_permissions')

    def test_user_add_page_uses_group_based_fields(self):
        response = self.client.get(reverse('admin:auth_user_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Primary access group')
        self.assertContains(response, 'Customer client')
        self.assertNotContains(response, 'User permissions')
        self.assertNotContains(response, 'Staff status')
        self.assertNotContains(response, 'Superuser status')

    def test_customer_group_creates_single_client_profile(self):
        user = self.User.objects.create_user(username='customer@example.com')

        profile = configure_user_from_primary_group(
            user,
            CUSTOMERS_GROUP,
            self.client_record,
        )

        user.refresh_from_db()
        self.assertEqual(primary_access_group_for(user), CUSTOMERS_GROUP)
        self.assertFalse(user.is_staff)
        self.assertEqual(
            profile.role,
            CalculatorUserProfile.Role.CUSTOMER_USER,
        )
        self.assertEqual(
            profile.client_scope,
            CalculatorUserProfile.ClientScope.SINGLE_CLIENT,
        )
        self.assertEqual(profile.client, self.client_record)

    def test_administrators_group_enables_staff_and_all_clients(self):
        user = self.User.objects.create_user(username='admin@example.com')

        profile = configure_user_from_primary_group(
            user,
            ADMINISTRATORS_GROUP,
        )

        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertEqual(primary_access_group_for(user), ADMINISTRATORS_GROUP)
        self.assertEqual(
            profile.role,
            CalculatorUserProfile.Role.INTERNAL_USER,
        )
        self.assertEqual(
            profile.client_scope,
            CalculatorUserProfile.ClientScope.ALL_CLIENTS,
        )

    def test_steadfast_group_has_calculator_but_not_admin(self):
        user = self.User.objects.create_user(username='staff@example.com')

        profile = configure_user_from_primary_group(
            user,
            STEADFAST_USERS_GROUP,
        )

        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertTrue(profile.calculator_access)
        self.assertEqual(
            profile.role,
            CalculatorUserProfile.Role.INTERNAL_USER,
        )
        self.assertEqual(
            profile.client_scope,
            CalculatorUserProfile.ClientScope.ALL_CLIENTS,
        )

    def test_changing_primary_group_removes_previous_primary_group(self):
        user = self.User.objects.create_user(username='changing@example.com')
        configure_user_from_primary_group(
            user,
            CUSTOMERS_GROUP,
            self.client_record,
        )

        configure_user_from_primary_group(user, STEADFAST_USERS_GROUP)

        user.refresh_from_db()
        self.assertEqual(primary_access_group_for(user), STEADFAST_USERS_GROUP)
        self.assertFalse(user.groups.filter(name=CUSTOMERS_GROUP).exists())
        self.assertFalse(user.is_staff)

    def test_customer_requires_active_client(self):
        user = self.User.objects.create_user(username='invalid@example.com')
        with self.assertRaises(ValidationError):
            configure_user_from_primary_group(user, CUSTOMERS_GROUP)

    def test_super_user_does_not_require_primary_group(self):
        result = configure_user_from_primary_group(
            self.superuser,
            ADMINISTRATORS_GROUP,
        )
        self.assertIsNone(result)
        self.assertFalse(
            self.superuser.groups.filter(
                name__in=(
                    ADMINISTRATORS_GROUP,
                    CUSTOMERS_GROUP,
                    STEADFAST_USERS_GROUP,
                )
            ).exists()
        )

    def test_group_permission_is_effective_without_individual_permission(self):
        permission = Permission.objects.get(
            content_type__app_label='clients',
            codename='view_client',
        )
        group = Group.objects.get(name=ADMINISTRATORS_GROUP)
        group.permissions.add(permission)
        user = self.User.objects.create_user(username='permission@example.com')
        configure_user_from_primary_group(user, ADMINISTRATORS_GROUP)

        self.assertTrue(user.has_perm('clients.view_client'))
        self.assertFalse(user.user_permissions.exists())

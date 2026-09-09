from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.authentication_gateway.admin import (
    CalculatorUserProfileInline,
    STHUserAdmin,
)
from apps.authentication_gateway.forms import CalculatorUserProfileInlineForm
from apps.authentication_gateway.models import CalculatorUserProfile
from apps.clients.models import Client


class IntegratedUserAdminTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.superuser = self.User.objects.create_superuser(
            username='technical-admin',
            email='technical@example.com',
            password='test-password',
        )
        self.client.force_login(self.superuser)
        self.client_record = Client.objects.create(code='STH', name='STH')
        self.request_factory = RequestFactory()

    def test_builtin_user_admin_is_replaced_by_sth_user_admin(self):
        model_admin = admin.site._registry[self.User]
        self.assertIsInstance(model_admin, STHUserAdmin)
        self.assertEqual(len(model_admin.inlines), 1)
        self.assertIs(model_admin.inlines[0].model, CalculatorUserProfile)

    def test_user_change_page_contains_calculator_access_block(self):
        user = self.User.objects.create_user(
            username='django-only',
            password='test-password',
        )
        response = self.client.get(
            reverse('admin:auth_user_change', args=[user.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Calculator access')
        self.assertContains(response, 'Enable calculator access')
        self.assertContains(response, 'calculator_profile-0-role')
        self.assertContains(response, 'calculator_profile-0-client_scope')

    def test_user_add_page_contains_optional_calculator_access_block(self):
        response = self.client.get(reverse('admin:auth_user_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Calculator access')
        self.assertContains(response, 'Enable calculator access')

    def test_new_inline_does_not_enable_access_by_default(self):
        form = CalculatorUserProfileInlineForm(
            instance=CalculatorUserProfile(user=self.superuser)
        )
        self.assertFalse(form.initial['calculator_access'])
        self.assertFalse(form.instance.calculator_access)

    def test_customer_inline_requires_one_active_client(self):
        user = self.User.objects.create_user(
            username='customer-user',
            password='test-password',
        )
        form = CalculatorUserProfileInlineForm(
            data={
                'user': str(user.pk),
                'role': CalculatorUserProfile.Role.CUSTOMER_USER,
                'client_scope': CalculatorUserProfile.ClientScope.SINGLE_CLIENT,
                'client': '',
                'calculator_access': 'on',
            },
            instance=CalculatorUserProfile(user=user),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('client', form.errors)

    def test_valid_customer_inline_can_create_profile(self):
        user = self.User.objects.create_user(
            username='valid-customer',
            password='test-password',
        )
        form = CalculatorUserProfileInlineForm(
            data={
                'user': str(user.pk),
                'role': CalculatorUserProfile.Role.CUSTOMER_USER,
                'client_scope': CalculatorUserProfile.ClientScope.SINGLE_CLIENT,
                'client': str(self.client_record.pk),
                'calculator_access': 'on',
            },
            instance=CalculatorUserProfile(user=user),
        )
        self.assertTrue(form.is_valid(), form.errors)
        profile = form.save()
        self.assertEqual(profile.user, user)
        self.assertEqual(profile.client, self.client_record)
        self.assertTrue(profile.calculator_access)


    def _profile_formset(self, user, data):
        request = self.request_factory.post('/admin/auth/user/')
        request.user = self.superuser
        inline = CalculatorUserProfileInline(self.User, admin.site)
        FormSet = inline.get_formset(request, obj=user)
        prefix = FormSet.get_default_prefix()
        complete_data = {
            f'{prefix}-TOTAL_FORMS': '1',
            f'{prefix}-INITIAL_FORMS': '0',
            f'{prefix}-MIN_NUM_FORMS': '0',
            f'{prefix}-MAX_NUM_FORMS': '1',
            f'{prefix}-0-id': '',
        }
        for key, value in data.items():
            complete_data[f'{prefix}-0-{key}'] = value
        return FormSet(data=complete_data, instance=user, prefix=prefix)

    def test_blank_inline_formset_does_not_create_profile(self):
        user = self.User.objects.create_user(
            username='technical-only',
            password='test-password',
        )
        formset = self._profile_formset(
            user,
            {
                'role': '',
                'client_scope': '',
                'client': '',
            },
        )
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        self.assertFalse(
            CalculatorUserProfile.objects.filter(user=user).exists()
        )

    def test_inline_formset_creates_customer_profile(self):
        user = self.User.objects.create_user(
            username='admin-created-customer',
            password='test-password',
        )
        formset = self._profile_formset(
            user,
            {
                'role': CalculatorUserProfile.Role.CUSTOMER_USER,
                'client_scope': CalculatorUserProfile.ClientScope.SINGLE_CLIENT,
                'client': str(self.client_record.pk),
                'calculator_access': 'on',
            },
        )
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        profile = CalculatorUserProfile.objects.get(user=user)
        self.assertEqual(profile.client, self.client_record)
        self.assertTrue(profile.calculator_access)

    def test_profile_model_is_hidden_from_admin_index(self):
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Calculator user profiles')

    def test_profile_diagnostic_url_remains_available_to_superuser(self):
        response = self.client.get(
            reverse(
                'admin:authentication_gateway_calculatoruserprofile_changelist'
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_user_list_distinguishes_missing_profile(self):
        user = self.User.objects.create_user(
            username='profile-missing',
            password='test-password',
        )
        model_admin = admin.site._registry[self.User]
        self.assertEqual(model_admin.calculator_status(user), 'Not configured')
        self.assertEqual(model_admin.calculator_role(user), '—')
        self.assertEqual(model_admin.calculator_clients(user), '—')

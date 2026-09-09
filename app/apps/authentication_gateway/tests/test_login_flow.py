from django.contrib.auth import get_user_model
from django.test import Client as TestClient
from django.test import TestCase
from django.urls import reverse

from apps.clients.models import Client

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.views import (
    CALCULATOR_ACCESS_MESSAGE,
    CSRF_SESSION_MESSAGE,
)


class CalculatorLoginFlowTests(TestCase):
    def setUp(self):
        self.sth = Client.objects.create(code='STH', name='STH')
        self.User = get_user_model()

    def _user(self, username='user@example.com', with_profile=False):
        user = self.User.objects.create_user(
            username=username,
            email=username,
            password='test-pass',
        )
        if with_profile:
            CalculatorUserProfile.objects.create(
                user=user,
                role=CalculatorUserProfile.Role.CUSTOMER_USER,
                client_scope=CalculatorUserProfile.ClientScope.SINGLE_CLIENT,
                client=self.sth,
            )
        return user

    def test_valid_credentials_without_profile_stay_on_login(self):
        self._user('no-profile@example.com')

        response = self.client.post(
            reverse('login'),
            {
                'username': 'no-profile@example.com',
                'password': 'test-pass',
                'next': reverse('freight_calculator'),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(response, CALCULATOR_ACCESS_MESSAGE)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_authenticated_user_without_profile_is_logged_out_and_redirected(self):
        user = self._user('old-user@example.com')
        self.client.force_login(user)

        response = self.client.get(reverse('freight_calculator'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(response, CALCULATOR_ACCESS_MESSAGE)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_invalid_credentials_keep_generic_login_message(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'unknown', 'password': 'wrong'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'The email/username or password is incorrect.',
        )
        self.assertNotContains(response, 'does not have a calculator access profile')

    def test_authorized_user_login_redirects_to_calculator(self):
        self._user('customer@example.com', with_profile=True)

        response = self.client.post(
            reverse('login'),
            {
                'username': 'customer@example.com',
                'password': 'test-pass',
                'next': reverse('freight_calculator'),
            },
        )

        self.assertRedirects(
            response,
            reverse('freight_calculator'),
            fetch_redirect_response=False,
        )
        self.assertIn('_auth_user_id', self.client.session)

    def test_logout_csrf_failure_uses_login_visual_message(self):
        user = self._user('customer2@example.com', with_profile=True)
        csrf_client = TestClient(enforce_csrf_checks=True)
        csrf_client.force_login(user)

        response = csrf_client.post(reverse('logout'))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(response, CSRF_SESSION_MESSAGE, status_code=403)
        self.assertNotContains(
            response,
            'CSRF verification failed. Request aborted.',
            status_code=403,
        )
    def test_login_template_preserves_approved_animation_hooks(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'css/login.css')
        self.assertContains(response, 'login-wrapper fadeInDown')
        self.assertContains(response, 'fadeIn first')
        self.assertContains(response, 'fadeIn second')
        self.assertContains(response, 'fadeIn third')
        self.assertContains(response, 'fadeIn fourth')

        invalid_response = self.client.post(
            reverse('login'),
            {'username': 'unknown', 'password': 'wrong'},
        )
        self.assertContains(invalid_response, 'login-feedback')


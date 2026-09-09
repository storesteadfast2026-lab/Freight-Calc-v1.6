"""Security regression tests for calculator login responses."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.authentication_gateway.forms import GENERIC_LOGIN_ERROR
from apps.authentication_gateway.models import CalculatorUserProfile
from apps.clients.models import Client


class CalculatorLoginSecurityTests(TestCase):
    password = "A-long-test-password-2026!"

    def setUp(self):
        self.client_record = Client.objects.create(
            code="STH",
            name="Steadfast",
            active=True,
        )
        self.login_url = reverse("login")

    def _user(self, username: str):
        return get_user_model().objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=self.password,
        )

    def _post_login(self, username: str, password: str):
        return self.client.post(
            self.login_url,
            {"username": username, "password": password},
        )

    def assert_generic_rejection(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, GENERIC_LOGIN_ERROR)
        self.assertNotContains(
            response,
            "This user does not have a calculator access profile.",
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unknown_user_uses_generic_message(self):
        response = self._post_login("not-created", self.password)
        self.assert_generic_rejection(response)

    def test_wrong_password_uses_generic_message(self):
        self._user("existing")
        response = self._post_login("existing", "wrong-password")
        self.assert_generic_rejection(response)

    def test_valid_credentials_without_profile_use_generic_message(self):
        self._user("no-profile")
        response = self._post_login("no-profile", self.password)
        self.assert_generic_rejection(response)

    def test_disabled_calculator_access_uses_generic_message(self):
        user = self._user("disabled")
        CalculatorUserProfile.objects.create(
            user=user,
            role="CUSTOMER_USER",
            client_scope="SINGLE_CLIENT",
            client=self.client_record,
            calculator_access=False,
        )
        response = self._post_login("disabled", self.password)
        self.assert_generic_rejection(response)

    def test_valid_customer_user_logs_in(self):
        user = self._user("customer")
        CalculatorUserProfile.objects.create(
            user=user,
            role="CUSTOMER_USER",
            client_scope="SINGLE_CLIENT",
            client=self.client_record,
            calculator_access=True,
        )
        response = self._post_login("customer", self.password)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        self.assertEqual(
            str(self.client.session.get("_auth_user_id")),
            str(user.pk),
        )

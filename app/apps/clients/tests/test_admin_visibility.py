from django.contrib import admin
from django.test import SimpleTestCase

from apps.clients.models import Client, FreightCalculator


class ClientAdminVisibilityTests(SimpleTestCase):
    def test_client_remains_registered_in_admin(self):
        self.assertTrue(admin.site.is_registered(Client))

    def test_freight_calculator_is_not_registered_in_admin(self):
        self.assertFalse(admin.site.is_registered(FreightCalculator))

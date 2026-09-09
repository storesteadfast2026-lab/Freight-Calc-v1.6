from django.contrib import admin
from django.test import SimpleTestCase

from apps.products.models import Product, ProductKitComponent


class ProductAdminVisibilityTests(SimpleTestCase):
    def test_product_remains_registered_in_admin(self):
        self.assertTrue(admin.site.is_registered(Product))

    def test_product_kit_component_is_not_registered_in_admin(self):
        self.assertFalse(admin.site.is_registered(ProductKitComponent))

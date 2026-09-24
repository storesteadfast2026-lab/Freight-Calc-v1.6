from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from apps.clients.models import Client
from .identity import normalize_customer, valid_customer


class Product(models.Model):
    """Client SKU master equivalent to the SKUs worksheet."""
    FREIGHT_TYPES = [('P', 'Pallet'), ('C', 'Case/Carton')]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='products')
    # Empty only for records created before Translogic CUSTOMER was available.
    customer_code = models.CharField(max_length=100, blank=True, default='', db_index=True)
    sku = models.CharField(max_length=80)
    name = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)
    length_m = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0'))
    width_m = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0'))
    height_m = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0'))
    weight_kg = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0'))
    cubic_m3 = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal('0'))
    freight_type = models.CharField(max_length=1, choices=FREIGHT_TYPES, default='P')
    active = models.BooleanField(default=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = [('client', 'customer_code', 'sku')]
        indexes = [models.Index(fields=['client', 'customer_code', 'sku']), models.Index(fields=['client', 'name'])]

    def __str__(self):
        label = self.name or self.description or self.sku
        return f'{self.sku} - {label}'

    def clean(self):
        super().clean()
        self.customer_code = normalize_customer(self.customer_code)
        if self.customer_code and not valid_customer(self.customer_code):
            raise ValidationError({'customer_code': 'Use a valid Translogic CUSTOMER code.'})

    def save(self, *args, **kwargs):
        self.customer_code = normalize_customer(self.customer_code)
        if self.customer_code and not valid_customer(self.customer_code):
            raise ValidationError({'customer_code': 'Use a valid Translogic CUSTOMER code.'})
        return super().save(*args, **kwargs)


class ProductKitComponent(models.Model):
    """Initial kit-component equivalent for the SKU-Kits worksheet."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    parent_sku = models.CharField(max_length=80)
    component_sku = models.CharField(max_length=80)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta:
        unique_together = [('client', 'parent_sku', 'component_sku')]

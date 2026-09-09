from decimal import Decimal
from django.db import models
from apps.clients.models import Client


class Product(models.Model):
    """Client SKU master / Equivalente a hoja SKUs."""
    FREIGHT_TYPES = [('P', 'Pallet'), ('C', 'Case/Carton')]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='products')
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
        unique_together = [('client', 'sku')]
        indexes = [models.Index(fields=['client', 'sku']), models.Index(fields=['client', 'name'])]

    def __str__(self):
        label = self.name or self.description or self.sku
        return f'{self.sku} - {label}'


class ProductKitComponent(models.Model):
    """Kit component / Equivalente inicial para hoja SKU-Kits."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    parent_sku = models.CharField(max_length=80)
    component_sku = models.CharField(max_length=80)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta:
        unique_together = [('client', 'parent_sku', 'component_sku')]

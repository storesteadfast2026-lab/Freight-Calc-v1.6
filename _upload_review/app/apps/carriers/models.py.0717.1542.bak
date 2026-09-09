from decimal import Decimal
from django.db import models
from apps.clients.models import Client


class Carrier(models.Model):
    """Transport provider / Transportista."""
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=150, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return self.name or self.code


class CarrierService(models.Model):
    """Carrier + service combination / Combinación carrier + service."""
    carrier = models.ForeignKey(Carrier, on_delete=models.CASCADE, related_name='services')
    service_code = models.CharField(max_length=40)
    service_name = models.CharField(max_length=150, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = [('carrier', 'service_code')]
        ordering = ['carrier__code', 'service_code']

    @property
    def excel_key(self):
        return f'{self.carrier.code}{self.service_code}'

    def __str__(self):
        return f'{self.carrier.code} {self.service_code}'


class ClientCarrierConfig(models.Model):
    """Per-client carrier configuration / Equivalente a filas de FuelSurcharge.

    English: Most fields map to columns in FuelSurcharge G:AD.
    Español: La mayoría de campos replica columnas de FuelSurcharge G:AD.
    """
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='carrier_configs')
    carrier_service = models.ForeignKey(CarrierService, on_delete=models.CASCADE)
    customer_code = models.CharField(max_length=30, default='STH')
    ratecard = models.CharField(max_length=80, blank=True)
    fuel_levy = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal('0'))
    fuel_levy_source = models.CharField(max_length=30, default='LEGACY_WORKBOOK')
    fuel_levy_updated_at = models.DateTimeField(null=True, blank=True)
    fuel_data_file = models.ForeignKey(
        'imports.ExternalDataFile',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='carrier_configs',
    )
    extra_surcharge = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal('0'))
    uprate = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal('0'))
    cubic_conversion = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('0'))
    tailgate_enabled = models.BooleanField(default=False)
    warehouse_handling_enabled = models.BooleanField(default=False)
    fixed_handling_charge = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0'))
    hand_unload_enabled = models.BooleanField(default=False)
    subzone_enabled = models.BooleanField(default=False)
    area_enabled = models.BooleanField(default=False)
    overlength_enabled = models.BooleanField(default=False)
    pallet_enabled = models.BooleanField(default=True)
    carton_enabled = models.BooleanField(default=True)
    zone_enabled = models.BooleanField(default=True)
    postcode_zones_enabled = models.BooleanField(default=False)
    empty_rate_enabled = models.BooleanField(default=False)
    base_status = models.CharField(max_length=5, default='L')
    order_ready_rule = models.CharField(max_length=40, default='GOOD')
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = [('client', 'carrier_service')]
        ordering = ['client__code', 'carrier_service__carrier__code']

    def __str__(self):
        return f'{self.client.code} {self.carrier_service}'

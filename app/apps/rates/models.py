from decimal import Decimal
from django.db import models
from apps.clients.models import Client
from apps.carriers.models import Carrier, CarrierService


class FreightZone(models.Model):
    """Zone mapping equivalent to the ZONES worksheet."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='zones')
    carrier_service = models.ForeignKey(CarrierService, on_delete=models.CASCADE)
    suburb = models.CharField(max_length=120)
    state = models.CharField(max_length=10)
    postcode = models.CharField(max_length=10, blank=True)
    zone = models.CharField(max_length=40, blank=True)
    subzone = models.CharField(max_length=40, blank=True)
    area = models.CharField(max_length=80, blank=True)
    lookup_key_suburb = models.CharField(max_length=220, db_index=True, blank=True)
    lookup_key_postcode = models.CharField(max_length=220, db_index=True, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['client', 'suburb', 'state']), models.Index(fields=['client', 'postcode'])]

    def save(self, *args, **kwargs):
        carrier_key = self.carrier_service.excel_key
        self.lookup_key_suburb = f'{carrier_key}{self.suburb}{self.state}'.upper().strip()
        self.lookup_key_postcode = f'{carrier_key}{self.postcode}'.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.carrier_service} {self.suburb}, {self.state} -> {self.zone}'


class FreightRate(models.Model):
    """Rate-card row equivalent to the RATES worksheet."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='rates')
    carrier_service = models.ForeignKey(CarrierService, on_delete=models.CASCADE)
    zone = models.CharField(max_length=40, blank=True)
    subzone = models.CharField(max_length=40, blank=True)
    area = models.CharField(max_length=80, blank=True)
    weight_break = models.CharField(max_length=40, blank=True)
    freight_type = models.CharField(max_length=5, blank=True)  # P or C, follows Excel OtherBrk / AV value.
    customer_code = models.CharField(max_length=30, default='STH')
    minimum_charge = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    basic_charge = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    per_subsequent_basic = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    per_kg = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    overweight_charge = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    remote_charge = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    offshore_charge = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    overlength_charge = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    margin = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal('0'))
    lookup_key = models.CharField(max_length=260, db_index=True, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['client', 'lookup_key'])]

    def save(self, *args, **kwargs):
        self.lookup_key = ''.join([
            self.carrier_service.excel_key,
            self.zone or '', self.subzone or '', self.area or '',
            self.weight_break or '', self.customer_code or '', self.freight_type or ''
        ]).strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.client.code} {self.lookup_key}'


class CarrierTailgateCharge(models.Model):
    """Carrier tailgate table equivalent to SettingFlags!C33:H52."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='tailgate_charges')
    carrier = models.ForeignKey(Carrier, on_delete=models.CASCADE)
    minimum_charge = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0'))
    per_subsequent_charge = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0'))
    hand_unload_charge = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0'))

    class Meta:
        unique_together = [('client', 'carrier')]

    def __str__(self):
        return f'{self.client.code} {self.carrier.code} Tailgate'

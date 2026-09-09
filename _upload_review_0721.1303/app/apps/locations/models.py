from django.db import models
from apps.clients.models import Client


class FromAddress(models.Model):
    """Origin address configured by admin / Dirección FROM configurada por administrador."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='from_addresses')
    name = models.CharField(max_length=120)
    address_line_1 = models.CharField(max_length=180, blank=True)
    address_line_2 = models.CharField(max_length=180, blank=True)
    suburb = models.CharField(max_length=120)
    state = models.CharField(max_length=10)
    postcode = models.CharField(max_length=10)
    country = models.CharField(max_length=80, default='Australia')
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['client__code', '-is_default', 'name']

    def __str__(self):
        return f'{self.name} - {self.suburb} {self.state} {self.postcode}'


class Suburb(models.Model):
    """Australian suburb lookup / Equivalente a hoja SUBURBS."""
    suburb_name = models.CharField(max_length=120)
    state = models.CharField(max_length=10)
    postcode = models.CharField(max_length=10)
    normalized_key = models.CharField(max_length=180, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['suburb_name', 'state']),
            models.Index(fields=['state', 'postcode']),
        ]
        unique_together = [('suburb_name', 'state', 'postcode')]
        ordering = ['state', 'suburb_name', 'postcode']

    def save(self, *args, **kwargs):
        self.normalized_key = f'{self.state}{self.suburb_name}'.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.suburb_name}, {self.state} {self.postcode}'

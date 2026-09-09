from django.db import models


class Client(models.Model):
    """Customer account / Cliente propietario de una calculadora."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name}'


class FreightCalculator(models.Model):
    """Calculator configuration by client / Configuración de calculadora por cliente."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='calculators')
    name = models.CharField(max_length=150)
    version = models.CharField(max_length=80, blank=True)
    calculation_engine_key = models.CharField(max_length=80, default='sth_v2026_r2')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('client', 'name', 'version')]

    def __str__(self):
        return f'{self.client.code} / {self.name} {self.version}'

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Client(models.Model):
    """Customer account that owns a calculator."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Calculator Customer'
        verbose_name_plural = 'Calculator Customers'

    def __str__(self):
        return f'{self.code} - {self.name}'


class FreightCalculator(models.Model):
    """Calculator configuration for each client."""
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


class Customer(models.Model):
    """Translogic customer master; independent of Calculator Customers."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    group = models.CharField(max_length=40, blank=True)
    group1 = models.CharField(max_length=40, blank=True)
    group2 = models.CharField(max_length=40, blank=True)
    their_code = models.CharField(max_length=40, blank=True)
    wh_pick_code = models.CharField(max_length=40, blank=True)
    acn = models.CharField(max_length=40, blank=True)
    abn = models.CharField(max_length=40, blank=True)
    gst_code = models.CharField(max_length=40, blank=True)
    sett_days = models.PositiveSmallIntegerField(null=True, blank=True)
    paydays_type = models.CharField(max_length=40, blank=True)
    source_date = models.DateField(null=True, blank=True)
    source_user = models.CharField(max_length=80, blank=True)
    is_special = models.BooleanField(default=False)
    source_row_number = models.PositiveIntegerField()
    raw_data = models.JSONField(default=dict)
    linked_client = models.OneToOneField(
        Client, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='translogic_customer', verbose_name='Calculator Customer',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'
        constraints = [
            models.CheckConstraint(
                condition=Q(is_special=False) | Q(linked_client__isnull=True),
                name='clients_special_customer_unlinked',
            ),
        ]

    def clean(self):
        super().clean()
        if self.is_special and self.linked_client_id:
            raise ValidationError({'linked_client': 'The special Customer cannot be linked to a Calculator Customer.'})

    def __str__(self):
        return f'{self.code} — {self.name}'


def customer_import_upload_to(instance, filename):
    return f'customer_imports/{instance.pk}/{filename}'


class CustomerImport(models.Model):
    """Durable history of a confirmed Customer import."""

    filename = models.CharField(max_length=255)
    source_file = models.FileField(upload_to=customer_import_upload_to)
    sha256 = models.CharField(max_length=64)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    total_rows = models.PositiveIntegerField()
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    missing_count = models.PositiveIntegerField(default=0)
    invalid_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    special_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, default='IMPORTED')
    details = models.JSONField(default=dict)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Customer import'

    def __str__(self):
        return f'{self.filename} — {self.uploaded_at:%Y-%m-%d %H:%M}'

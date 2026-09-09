from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.clients.models import Client


def external_data_upload_to(instance, filename):
    """Build a stable, versioned path for uploaded/downloaded source files."""
    timestamp = timezone.localtime().strftime('%Y%m%d_%H%M%S')
    safe_name = Path(filename).name.replace(' ', '_')
    client_code = getattr(instance.client, 'code', 'unknown').lower()
    file_type = (instance.file_type or 'other').lower()
    return f'external_imports/{client_code}/{file_type}/{timezone.localdate():%Y/%m}/{timestamp}_{safe_name}'


class ExternalDataFile(models.Model):
    """Uploaded or downloaded external source with validation/import history."""

    FILE_TYPES = [
        ('PRODUCTS', 'Products'),
        ('STOCK', 'Stock'),
        ('FUEL', 'Fuel'),
        ('ZONES', 'Zones'),
        ('RATES', 'Rates'),
        ('SUBURBS', 'Suburbs'),
        ('WORKBOOK', 'Full Excel Workbook'),
    ]
    SOURCE_METHODS = [
        ('ADMIN_UPLOAD', 'Admin upload'),
        ('ADMIN_WEB_FETCH', 'Admin web fetch'),
        ('COMMAND', 'Management command'),
    ]
    STATUSES = [
        ('UPLOADED', 'Uploaded'),
        ('DOWNLOADED', 'Downloaded'),
        ('VALIDATED', 'Validated'),
        ('VALIDATION_FAILED', 'Validation failed'),
        ('ACTIVE', 'Active'),
        ('IMPORT_FAILED', 'Import failed'),
        ('ROLLED_BACK', 'Rolled back'),
        ('IMPORTED', 'Imported'),
        ('ERROR', 'Error'),
        ('ARCHIVED', 'Archived'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='external_files')
    file_type = models.CharField(max_length=30, choices=FILE_TYPES)
    source_method = models.CharField(max_length=30, choices=SOURCE_METHODS, default='ADMIN_UPLOAD')
    source_url = models.URLField(max_length=1000, blank=True)
    original_filename = models.CharField(max_length=255)
    uploaded_file = models.FileField(upload_to=external_data_upload_to, null=True, blank=True)
    # Kept for backwards compatibility with command-created workbook records.
    stored_path = models.CharField(max_length=500, blank=True, default='')
    file_size_bytes = models.PositiveBigIntegerField(default=0)
    mime_type = models.CharField(max_length=120, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    notes = models.TextField(blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='external_files_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=30, choices=STATUSES, default='UPLOADED', db_index=True)

    validation_summary = models.JSONField(default=dict, blank=True)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='external_files_validated',
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='external_files_imported',
    )
    last_imported_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='external_files_activated',
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    rolled_back_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='external_files_rolled_back',
    )
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    previous_active_file = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='replacement_files',
    )

    import_summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        permissions = [
            ('validate_external_data_file', 'Can validate external data files'),
            ('activate_fuel', 'Can activate fuel rates'),
            ('rollback_fuel', 'Can rollback fuel rates'),
            ('download_external_data_file', 'Can download external data files'),
        ]

    def __str__(self):
        return f'{self.client.code} {self.file_type} {self.original_filename}'

    @property
    def local_path(self):
        if self.uploaded_file:
            try:
                return self.uploaded_file.path
            except (NotImplementedError, ValueError):
                return ''
        return self.stored_path


class ProductSourceRow(models.Model):
    """Read-only staging row loaded from product_sth.xlsx."""

    external_file = models.ForeignKey(
        ExternalDataFile,
        on_delete=models.CASCADE,
        related_name='product_source_rows',
        limit_choices_to={'file_type': 'PRODUCTS'},
    )
    source_row_number = models.PositiveIntegerField()
    product_code_raw = models.CharField(max_length=255)
    product_code_normalized = models.CharField(max_length=255, db_index=True)
    name = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=255, blank=True)
    length_mm = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    width_mm = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    height_mm = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    cubic_m3 = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    quantity = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    pallet = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    comment = models.TextField(blank=True)
    source_status = models.CharField(max_length=100, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    validation_errors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['source_row_number']
        constraints = [
            models.UniqueConstraint(
                fields=['external_file', 'source_row_number'],
                name='imports_product_source_file_row_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['external_file', 'product_code_normalized'], name='imp_prod_file_sku_idx'),
        ]

    def __str__(self):
        return f'{self.external_file_id}:{self.source_row_number} {self.product_code_normalized}'


class StockSourceRow(models.Model):
    """Read-only staging row loaded from stock_sth.xlsx."""

    external_file = models.ForeignKey(
        ExternalDataFile,
        on_delete=models.CASCADE,
        related_name='stock_source_rows',
        limit_choices_to={'file_type': 'STOCK'},
    )
    source_row_number = models.PositiveIntegerField()
    movement_number = models.CharField(max_length=100, blank=True)
    stock_date_raw = models.CharField(max_length=100, blank=True)
    customer = models.CharField(max_length=100, blank=True)
    product_code_raw = models.CharField(max_length=255)
    product_code_normalized = models.CharField(max_length=255, db_index=True)
    sql_name = models.CharField(max_length=500, blank=True)
    quantity = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    pallet = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    group1 = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)
    stock_class = models.CharField(max_length=255, blank=True)
    sql_stock_ref = models.CharField(max_length=255, blank=True)
    weight_kg = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    cubic_m3 = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    depot = models.CharField(max_length=255, blank=True)
    sql_group = models.CharField(max_length=255, blank=True)
    sql_group1 = models.CharField(max_length=255, blank=True)
    expiry_raw = models.CharField(max_length=100, blank=True)
    pallet_ref = models.CharField(max_length=255, blank=True)
    serial_no = models.CharField(max_length=255, blank=True)
    source_status = models.CharField(max_length=100, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    validation_errors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['source_row_number']
        constraints = [
            models.UniqueConstraint(
                fields=['external_file', 'source_row_number'],
                name='imports_stock_source_file_row_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['external_file', 'product_code_normalized'], name='imp_stock_file_sku_idx'),
        ]

    def __str__(self):
        return f'{self.external_file_id}:{self.source_row_number} {self.product_code_normalized}'

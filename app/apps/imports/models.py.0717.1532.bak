from django.conf import settings
from django.db import models
from apps.clients.models import Client


class ExternalDataFile(models.Model):
    """Uploaded external source / Archivo externo administrado."""
    FILE_TYPES = [
        ('PRODUCTS', 'Products'), ('STOCK', 'Stock'), ('FUEL', 'Fuel'),
        ('ZONES', 'Zones'), ('RATES', 'Rates'), ('SUBURBS', 'Suburbs'), ('WORKBOOK', 'Full Excel Workbook')
    ]
    STATUSES = [('UPLOADED', 'Uploaded'), ('IMPORTED', 'Imported'), ('ERROR', 'Error'), ('ARCHIVED', 'Archived')]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='external_files')
    file_type = models.CharField(max_length=30, choices=FILE_TYPES)
    original_filename = models.CharField(max_length=255)
    stored_path = models.CharField(max_length=500)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUSES, default='UPLOADED')
    last_imported_at = models.DateTimeField(null=True, blank=True)
    import_summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.client.code} {self.file_type} {self.original_filename}'

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """Immutable application audit log exposed as read-only in Django Admin."""

    SEVERITIES = [
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical'),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    client = models.ForeignKey(
        'clients.Client',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_events',
    )
    external_file = models.ForeignKey(
        'imports.ExternalDataFile',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_events',
    )
    event_type = models.CharField(max_length=80, db_index=True)
    severity = models.CharField(max_length=12, choices=SEVERITIES, default='INFO', db_index=True)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.event_type} {self.created_at:%Y-%m-%d %H:%M}'

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """Generic audit log / Registro de auditoría."""
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=80)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.event_type} {self.created_at:%Y-%m-%d %H:%M}'

from django.conf import settings
from django.db import models


class SavedEstimate(models.Model):
    """Immutable calculation snapshot created outside the freight engine."""

    reference = models.CharField(max_length=32, unique=True)
    client = models.ForeignKey(
        'clients.Client',
        on_delete=models.PROTECT,
        related_name='saved_estimates',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='saved_freight_estimates',
    )
    created_by_label = models.CharField(max_length=254)
    schema_version = models.PositiveSmallIntegerField(default=1)
    input_snapshot = models.JSONField()
    result_snapshot = models.JSONField()
    destination_label = models.CharField(max_length=220, blank=True)
    total_weight_kg = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        null=True,
        blank=True,
    )
    total_cubic_m3 = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        null=True,
        blank=True,
    )
    best_estimate_ex_gst = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    selected_option_index = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['client', '-created_at'], name='saved_est_client_created'),
            models.Index(fields=['created_by', '-created_at'], name='saved_est_user_created'),
        ]

    def __str__(self):
        return f'{self.reference} / {self.client.code}'


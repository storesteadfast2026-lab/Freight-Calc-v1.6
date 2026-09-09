from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class CalculatorUserProfile(models.Model):
    """Calculator role and client scope attached to Django's built-in user."""

    class Role(models.TextChoices):
        CUSTOMER_USER = 'CUSTOMER_USER', 'Customer User'
        INTERNAL_USER = 'INTERNAL_USER', 'Internal User'

    class ClientScope(models.TextChoices):
        SINGLE_CLIENT = 'SINGLE_CLIENT', 'Single client'
        ALL_CLIENTS = 'ALL_CLIENTS', 'All clients'
        SELECTED_CLIENTS = 'SELECTED_CLIENTS', 'Selected clients'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='calculator_profile',
    )
    role = models.CharField(max_length=30, choices=Role.choices)
    client_scope = models.CharField(max_length=30, choices=ClientScope.choices)
    client = models.ForeignKey(
        'clients.Client',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='customer_users',
        help_text='Required only for Customer User.',
    )
    allowed_clients = models.ManyToManyField(
        'clients.Client',
        blank=True,
        related_name='authorized_internal_users',
        help_text='Used only for Internal User with Selected clients scope.',
    )
    calculator_access = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__username']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        role='CUSTOMER_USER',
                        client_scope='SINGLE_CLIENT',
                        client__isnull=False,
                    )
                    | Q(
                        role='INTERNAL_USER',
                        client_scope__in=['ALL_CLIENTS', 'SELECTED_CLIENTS'],
                        client__isnull=True,
                    )
                ),
                name='authgw_profile_role_scope_client_valid',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.role == self.Role.CUSTOMER_USER:
            if self.client_scope != self.ClientScope.SINGLE_CLIENT:
                errors['client_scope'] = 'Customer User must use Single client scope.'
            if self.client_id is None:
                errors['client'] = 'Customer User requires one client.'
            elif not self.client.active:
                errors['client'] = 'Customer User client must be active.'
            if self.user_id and self.user.is_staff:
                errors['user'] = 'Customer User cannot have Django Admin access.'

        elif self.role == self.Role.INTERNAL_USER:
            if self.client_scope not in {
                self.ClientScope.ALL_CLIENTS,
                self.ClientScope.SELECTED_CLIENTS,
            }:
                errors['client_scope'] = (
                    'Internal User must use All clients or Selected clients scope.'
                )
            if self.client_id is not None:
                errors['client'] = 'Internal User must not use the single client field.'

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.user.get_username()} / {self.get_role_display()}'

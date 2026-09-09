from django import forms
from django.core.exceptions import ValidationError

from .models import CalculatorUserProfile


class CalculatorUserProfileAdminForm(forms.ModelForm):
    class Meta:
        model = CalculatorUserProfile
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get('role')
        scope = cleaned.get('client_scope')
        client = cleaned.get('client')
        allowed_clients = cleaned.get('allowed_clients')
        user = cleaned.get('user')

        if role == CalculatorUserProfile.Role.CUSTOMER_USER:
            if scope != CalculatorUserProfile.ClientScope.SINGLE_CLIENT:
                self.add_error('client_scope', 'Customer User must use Single client scope.')
            if not client:
                self.add_error('client', 'Customer User requires one active client.')
            elif not client.active:
                self.add_error('client', 'Customer User client must be active.')
            if allowed_clients:
                self.add_error(
                    'allowed_clients',
                    'Customer User cannot have selected internal clients.',
                )
            if user and user.is_staff:
                self.add_error('user', 'Customer User cannot have Django Admin access.')

        if role == CalculatorUserProfile.Role.INTERNAL_USER:
            if client:
                self.add_error('client', 'Internal User must not use the single client field.')
            if scope == CalculatorUserProfile.ClientScope.SELECTED_CLIENTS:
                if not allowed_clients:
                    self.add_error(
                        'allowed_clients',
                        'Selected clients scope requires at least one active client.',
                    )
                elif allowed_clients.filter(active=False).exists():
                    self.add_error('allowed_clients', 'All selected clients must be active.')
            elif scope == CalculatorUserProfile.ClientScope.ALL_CLIENTS:
                if allowed_clients:
                    self.add_error(
                        'allowed_clients',
                        'All clients scope must not include a selected-client list.',
                    )
            else:
                self.add_error(
                    'client_scope',
                    'Internal User must use All clients or Selected clients scope.',
                )

            if user and user.is_staff and not user.is_superuser:
                if scope != CalculatorUserProfile.ClientScope.ALL_CLIENTS:
                    self.add_error(
                        'client_scope',
                        'A normal Django Administrator must be Internal User / All clients.',
                    )

        if user and not user.is_active and cleaned.get('calculator_access'):
            raise ValidationError(
                'Inactive Django users cannot have effective calculator access. '
                'Disable calculator access or reactivate the user.'
            )

        return cleaned

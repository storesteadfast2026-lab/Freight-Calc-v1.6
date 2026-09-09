from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError

from apps.clients.models import Client

from .models import CalculatorUserProfile
from .services import (
    ADMINISTRATORS_GROUP,
    CUSTOMERS_GROUP,
    PRIMARY_ACCESS_GROUPS,
    STEADFAST_USERS_GROUP,
    primary_access_group_for,
)


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


PRIMARY_ACCESS_GROUP_CHOICES = (
    (ADMINISTRATORS_GROUP, 'Administrators — Calculator and operational Django Admin'),
    (CUSTOMERS_GROUP, 'Customers — Calculator for one client'),
    (STEADFAST_USERS_GROUP, 'Steadfast Users — Internal calculator access'),
)


def _primary_access_group_field():
    return forms.ChoiceField(
        label='Primary access group',
        choices=PRIMARY_ACCESS_GROUP_CHOICES,
        required=True,
        help_text=(
            'Permissions are inherited from this group. Individual user '
            'permissions are disabled.'
        ),
    )


def _calculator_client_field():
    return forms.ModelChoiceField(
        label='Customer client',
        queryset=Client.objects.none(),
        required=False,
        help_text='Required only for Customers.',
    )


class PrimaryAccessFieldsMixin:
    """Clear group-based access behaviour shared by User add/change forms."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['calculator_client'].queryset = Client.objects.filter(
            active=True
        ).order_by('code')

        user = self.instance
        if user and user.pk:
            if user.is_superuser:
                self.fields['primary_access_group'].required = False
                self.fields['primary_access_group'].disabled = True
                self.fields['calculator_client'].disabled = True
                self.fields['primary_access_group'].help_text = (
                    'Super User access comes from Django is_superuser and does '
                    'not require a primary access group.'
                )
            else:
                try:
                    self.initial['primary_access_group'] = primary_access_group_for(user)
                except ValidationError:
                    # Preserve a visible validation error in clean() without
                    # guessing which conflicting group should win.
                    self.initial['primary_access_group'] = ''

            try:
                profile = user.calculator_profile
            except CalculatorUserProfile.DoesNotExist:
                profile = None
            if profile and profile.role == CalculatorUserProfile.Role.CUSTOMER_USER:
                self.initial['calculator_client'] = profile.client_id

    def clean(self):
        cleaned = super().clean()
        user = self.instance
        if user and user.pk and user.is_superuser:
            return cleaned

        group_name = cleaned.get('primary_access_group')
        client = cleaned.get('calculator_client')
        if group_name not in PRIMARY_ACCESS_GROUPS:
            self.add_error('primary_access_group', 'Select one primary access group.')
        elif group_name == CUSTOMERS_GROUP:
            if client is None:
                self.add_error(
                    'calculator_client',
                    'Customers require one active client.',
                )
        elif client is not None:
            self.add_error(
                'calculator_client',
                'Only Customers use the single Customer client field.',
            )
        return cleaned


class STHUserCreationForm(PrimaryAccessFieldsMixin, UserCreationForm):
    primary_access_group = _primary_access_group_field()
    calculator_client = _calculator_client_field()

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'email', 'first_name', 'last_name', 'is_active')


class STHUserChangeForm(PrimaryAccessFieldsMixin, UserChangeForm):
    primary_access_group = _primary_access_group_field()
    calculator_client = _calculator_client_field()

    class Meta(UserChangeForm.Meta):
        model = get_user_model()
        fields = ('username', 'email', 'first_name', 'last_name', 'is_active')


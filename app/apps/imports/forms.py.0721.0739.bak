from django import forms

from apps.clients.models import Client
from apps.imports.models import ExternalDataFile


class ExternalDataFileAdminForm(forms.ModelForm):
    file_type = forms.ChoiceField(choices=[('FUEL', 'Fuel')], initial='FUEL')

    class Meta:
        model = ExternalDataFile
        fields = ('client', 'file_type', 'uploaded_file', 'notes')

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data.get('uploaded_file')
        if self.instance.pk and uploaded_file is None:
            return self.instance.uploaded_file
        if uploaded_file is None:
            raise forms.ValidationError('Select a fuel CSV file.')
        if not uploaded_file.name.lower().endswith('.csv'):
            raise forms.ValidationError('The fuel file must use the .csv extension.')
        return uploaded_file


class FetchFuelForm(forms.Form):
    client = forms.ModelChoiceField(queryset=Client.objects.filter(active=True).order_by('code'))
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional reason or note for this manual fetch.',
    )


class FuelActivationForm(forms.Form):
    force_expired = forms.BooleanField(
        required=False,
        help_text='Superusers only. Use only when the source expiry date has passed.',
    )
    justification = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Required when forcing activation of an expired dataset.',
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not getattr(user, 'is_superuser', False):
            self.fields['force_expired'].disabled = True

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('force_expired') and not cleaned.get('justification', '').strip():
            self.add_error('justification', 'Enter a justification for forced activation.')
        return cleaned


class FuelRollbackForm(forms.Form):
    reason = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Explain why the active fuel dataset is being rolled back.',
    )

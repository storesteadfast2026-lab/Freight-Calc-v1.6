from django import forms
from django.core.validators import URLValidator

from apps.clients.models import Client
from apps.imports.models import ExternalDataFile


class ExternalDataFileAdminForm(forms.ModelForm):
    file_type = forms.ChoiceField(
        choices=[
            ('FUEL', 'Fuel CSV'),
            ('PRODUCTS', 'STH product source (product_sth.xlsx)'),
            ('STOCK', 'STH stock source (stock_sth.xlsx)'),
        ],
        initial='FUEL',
    )

    class Meta:
        model = ExternalDataFile
        fields = ('client', 'file_type', 'uploaded_file', 'notes')

    def clean(self):
        cleaned = super().clean()
        uploaded_file = cleaned.get('uploaded_file')
        file_type = cleaned.get('file_type')

        if self.instance.pk and uploaded_file is None:
            return cleaned
        if uploaded_file is None:
            self.add_error('uploaded_file', 'Select a source file.')
            return cleaned

        filename = uploaded_file.name.lower()
        if file_type == 'FUEL' and not filename.endswith('.csv'):
            self.add_error('uploaded_file', 'The fuel file must use the .csv extension.')
        if file_type in {'PRODUCTS', 'STOCK'} and not filename.endswith('.xlsx'):
            self.add_error('uploaded_file', 'Product and stock source files must use the .xlsx extension.')
        return cleaned


class SourceUploadForm(forms.Form):
    client = forms.ModelChoiceField(queryset=Client.objects.filter(active=True).order_by('code'))
    uploaded_file = forms.FileField()
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional note for this manual reference-data upload.',
    )

    def __init__(self, *args, expected_filename='', **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_filename = expected_filename
        if expected_filename:
            self.fields['uploaded_file'].help_text = f'Expected source: {expected_filename}'

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data['uploaded_file']
        if not uploaded_file.name.lower().endswith('.xlsx'):
            raise forms.ValidationError('The source file must use the .xlsx extension.')
        return uploaded_file


class FetchFuelForm(forms.Form):
    client = forms.ModelChoiceField(queryset=Client.objects.filter(active=True).order_by('code'))
    source_url = forms.URLField(
        label='Fuel source URL',
        max_length=1000,
        validators=[URLValidator(schemes=('http', 'https'))],
        widget=forms.URLInput(attrs={'size': 100}),
        help_text='The last validated URL for the selected client is remembered for future fetches.',
    )
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

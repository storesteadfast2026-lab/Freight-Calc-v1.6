from django import forms
from django.core.validators import URLValidator

from apps.clients.models import Client
from apps.imports.models import ExternalDataFile, ProductSourceRejectedRow, ProductSourceRow
from apps.imports.services.product_repair import build_product_repair_proposal
from apps.imports.services.xlsx_reader import normalize_product_sku


class ProductSourceRejectedRowReviewForm(forms.ModelForm):
    code = forms.CharField(label='Product code', max_length=255)
    name = forms.CharField(max_length=500, required=False)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
    category = forms.CharField(max_length=255, required=False)
    length_mm = forms.DecimalField(required=False, min_value=0, max_digits=20, decimal_places=6)
    width_mm = forms.DecimalField(required=False, min_value=0, max_digits=20, decimal_places=6)
    height_mm = forms.DecimalField(required=False, min_value=0, max_digits=20, decimal_places=6)
    cubic_m3 = forms.DecimalField(required=False, min_value=0, max_digits=20, decimal_places=6)
    quantity = forms.DecimalField(required=False, min_value=0, max_digits=20, decimal_places=6)
    weight_kg = forms.DecimalField(required=False, min_value=0, max_digits=20, decimal_places=6)
    pallet = forms.DecimalField(required=False, min_value=0, max_digits=20, decimal_places=6)
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
    source_status = forms.CharField(label='Source status', max_length=100, required=False)

    class Meta:
        model = ProductSourceRejectedRow
        fields = ('review_note',)
        widgets = {'review_note': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        proposal = dict(self.instance.proposed_data or {})
        if not proposal:
            proposal = build_product_repair_proposal(self.instance.raw_values or [])
        for field_name in (
            'code', 'name', 'description', 'category', 'length_mm', 'width_mm',
            'height_mm', 'cubic_m3', 'quantity', 'weight_kg', 'pallet', 'comment',
            'source_status',
        ):
            if field_name not in self.initial:
                self.fields[field_name].initial = proposal.get(field_name, '')
        if self.instance.repair_status == 'APPROVED':
            for field in self.fields.values():
                field.disabled = True

    def clean(self):
        cleaned = super().clean()
        approving = '_approve_repair' in self.data or '_approve_selected' in self.data
        if approving and self.instance.repair_status == 'APPROVED':
            raise forms.ValidationError('This repair is already approved and cannot be changed.')
        if approving and not str(cleaned.get('review_note') or '').strip():
            self.add_error('review_note', 'A review note is required for approval.')
        if approving:
            code = normalize_product_sku(cleaned.get('code'))
            if not code:
                self.add_error('code', 'Product code is required.')
            elif ProductSourceRow.objects.filter(
                external_file=self.instance.external_file,
                product_code_normalized=code,
            ).exists():
                self.add_error(
                    'code',
                    f'Product code {code} already exists in valid staging for this file.',
                )
        return cleaned

    def repair_payload(self):
        return {
            field_name: self.cleaned_data.get(field_name)
            for field_name in (
                'code', 'name', 'description', 'category', 'length_mm', 'width_mm',
                'height_mm', 'cubic_m3', 'quantity', 'weight_kg', 'pallet', 'comment',
                'source_status',
            )
        }


class ExternalDataFileAdminForm(forms.ModelForm):
    file_type = forms.ChoiceField(
        choices=[
            ('FUEL', 'Fuel CSV'),
            ('PRODUCTS', 'STH product source (products.csv)'),
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
        if file_type == 'PRODUCTS' and not filename.endswith(('.csv', '.xlsx')):
            self.add_error('uploaded_file', 'The product source must use the .csv or .xlsx extension.')
        if file_type == 'STOCK' and not filename.endswith('.xlsx'):
            self.add_error('uploaded_file', 'The stock source must use the .xlsx extension.')
        return cleaned


class SourceUploadForm(forms.Form):
    client = forms.ModelChoiceField(queryset=Client.objects.filter(active=True).order_by('code'))
    uploaded_file = forms.FileField()
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional note for this manual reference-data upload.',
    )

    def __init__(self, *args, expected_filename='', allowed_extensions=('.xlsx',), **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_filename = expected_filename
        self.allowed_extensions = tuple(extension.lower() for extension in allowed_extensions)
        if expected_filename:
            self.fields['uploaded_file'].help_text = f'Expected source: {expected_filename}'

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data['uploaded_file']
        if not uploaded_file.name.lower().endswith(self.allowed_extensions):
            allowed = ' or '.join(self.allowed_extensions)
            raise forms.ValidationError(f'The source file must use {allowed}.')
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

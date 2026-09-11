from .admin_postcodes_apply import PostcodesApplyAdminMixin
import json
import mimetypes
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.clients.models import Client
from apps.imports.admin_ftp_inbox import FtpInboxAdminMixin
from apps.imports.forms import (
    ExternalDataFileAdminForm,
    FetchFuelForm,
    FuelActivationForm,
    FuelRollbackForm,
    SourceUploadForm,
)
from apps.imports.models import (
    ExternalDataFile,
    ExternalDataReviewItem,
    ProductSourceRow,
    StockSourceRow,
)
from apps.imports.services.audit import create_audit_event
from apps.imports.services.fuel import (
    FuelImportError,
    activate_fuel_file,
    calculate_sha256,
    create_downloaded_fuel_file,
    default_fuel_source_url,
    remembered_fuel_source_url,
    rollback_fuel_file,
    validate_fuel_file,
)
from apps.imports.services.review import sync_postcodes_review_items
from apps.imports.services.product_source import validate_product_source_file
from apps.imports.services.stock_source import validate_stock_source_file
from apps.imports.services.xlsx_reader import SourceImportError


REFERENCE_FILE_TYPES = {'PRODUCTS', 'STOCK'}



class HistoricalMatchSelect(forms.Select):
    """Select widget that exposes the selected historical row to Admin JavaScript."""

    match_map = {}

    def create_option(
        self,
        name,
        value,
        label,
        selected,
        index,
        subindex=None,
        attrs=None,
    ):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        match = self.match_map.get(str(value))
        if match:
            option['attrs']['data-suburb'] = str(match.get('suburb') or '')
            option['attrs']['data-state'] = str(match.get('state') or '')
            option['attrs']['data-postcode'] = str(match.get('postcode') or '')
        return option


class PostcodesReviewControlsWidget(forms.MultiWidget):
    template_name = 'admin/imports/widgets/postcodes_review_controls.html'

    def __init__(self, attrs=None):
        widgets = (
            forms.TextInput(
                attrs={
                    'class': 'postcodes-review-note',
                    'placeholder': 'Review note',
                    'style': 'width:150px;',
                }
            ),
            forms.TextInput(
                attrs={
                    'class': 'postcodes-override-suburb',
                    'placeholder': 'Suburb',
                    'style': 'width:125px;',
                }
            ),
            forms.TextInput(
                attrs={
                    'class': 'postcodes-override-state',
                    'placeholder': 'State',
                    'maxlength': 10,
                    'style': 'width:48px;',
                }
            ),
            forms.TextInput(
                attrs={
                    'class': 'postcodes-override-postcode',
                    'placeholder': 'Postcode',
                    'maxlength': 10,
                    'style': 'width:62px;',
                }
            ),
        )
        super().__init__(widgets, attrs)

    def decompress(self, value):
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return list(value)
        return ['', '', '', '']


class PostcodesReviewControlsField(forms.MultiValueField):
    widget = PostcodesReviewControlsWidget

    def __init__(self, *args, **kwargs):
        fields = (
            forms.CharField(required=False),
            forms.CharField(required=False),
            forms.CharField(required=False),
            forms.CharField(required=False),
        )
        kwargs.setdefault('required', False)
        kwargs.setdefault('require_all_fields', False)
        super().__init__(fields=fields, *args, **kwargs)

    def compress(self, data_list):
        values = list(data_list or ['', '', '', ''])
        while len(values) < 4:
            values.append('')
        return values[:4]


class PostcodesReviewItemForm(forms.ModelForm):
    """Compact Postcodes Review form.

    postcodes.csv is authoritative. Current DB is reference/replace-target
    metadata only. Final values are implicit from the source unless the
    reviewer explicitly chooses Manual override.
    """

    DECISION_CHOICES = (
        ('PENDING', 'Pending'),
        ('ACCEPT_SOURCE', 'Use source file'),
        ('NEEDS_REVIEW', 'Needs review'),
        ('MANUAL_OVERRIDE', 'Manual override'),
    )

    LEGACY_DECISION_LABELS = {
        'KEEP': 'Legacy - Keep source (review again)',
        'USE_EXISTING_DB': 'Legacy - Use existing DB (review again)',
        'CORRECT_MANUALLY': 'Legacy - Correct manually (review again)',
        'REMOVE_ADDED_ROW': 'Legacy - Remove added row (review again)',
    }

    selected_historical_suburb_id = forms.ChoiceField(
        required=False,
        label='Current DB',
        widget=HistoricalMatchSelect(
            attrs={
                'class': 'postcodes-current-db',
                'style': 'width:220px; max-width:220px;',
            }
        ),
    )
    decision = forms.ChoiceField(
        choices=DECISION_CHOICES,
        widget=forms.Select(
            attrs={
                'class': 'postcodes-review-decision',
                'style': 'width:135px; max-width:135px;',
            }
        ),
    )
    review_controls = PostcodesReviewControlsField(
        required=False,
        label='Notes',
    )

    class Meta:
        model = ExternalDataReviewItem
        fields = (
            'selected_historical_suburb_id',
            'decision',
        )

    @staticmethod
    def _normalise_controls(value):
        controls = list(value or ['', '', '', ''])
        while len(controls) < 4:
            controls.append('')
        return controls[:4]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_data = getattr(self.instance, 'current_data', None) or {}
        matches = current_data.get('historical_matches') or []
        labels = {
            'EXACT_TRIPLET': 'exact',
            'SAME_SUBURB_STATE': 'same suburb',
            'VALIDATOR_ALIAS': 'alias',
        }

        match_map = {}
        choices = [('', '-- Select current DB row --')]
        for match in matches:
            raw_id = match.get('id')
            if raw_id is None:
                continue
            value = str(raw_id)
            match_map[value] = match
            label = '{} {} {} - {}'.format(
                match.get('suburb') or '-',
                match.get('state') or '-',
                match.get('postcode') or '-',
                labels.get(match.get('match_type'), 'match'),
            )
            choices.append((value, label))

        selected_id = getattr(
            self.instance,
            'selected_historical_suburb_id',
            None,
        )
        if selected_id is not None and str(selected_id) not in match_map:
            choices.append(
                (
                    str(selected_id),
                    f'Previously selected DB row #{selected_id}',
                )
            )

        db_field = self.fields['selected_historical_suburb_id']
        db_field.choices = choices
        if selected_id is not None:
            self.initial['selected_historical_suburb_id'] = str(selected_id)
        elif match_map:
            # UI convenience only. The first displayed Current DB candidate is
            # preselected, but source values remain authoritative.
            first_current_db_id = next(iter(match_map))
            self.initial['selected_historical_suburb_id'] = first_current_db_id

        if not match_map and selected_id is None:
            db_field.choices = [('', 'No direct current DB match')]
            db_field.disabled = True

        source = getattr(self.instance, 'source_data', None) or {}
        self.initial['review_controls'] = [
            str(getattr(self.instance, 'notes', '') or ''),
            str(
                getattr(self.instance, 'corrected_suburb', '')
                or source.get('suburb')
                or ''
            ),
            str(
                getattr(self.instance, 'corrected_state', '')
                or source.get('state')
                or ''
            ),
            str(
                getattr(self.instance, 'corrected_postcode', '')
                or source.get('postcode')
                or ''
            ),
        ]

        current_decision = str(getattr(self.instance, 'decision', '') or '')
        allowed = {value for value, _label in self.DECISION_CHOICES}
        if current_decision and current_decision not in allowed:
            legacy_label = self.LEGACY_DECISION_LABELS.get(
                current_decision,
                f'Legacy - {current_decision} (review again)',
            )
            self.fields['decision'].choices = (
                tuple(self.DECISION_CHOICES)
                + ((current_decision, legacy_label),)
            )

    def clean(self):
        cleaned = super().clean()

        controls = self._normalise_controls(
            cleaned.get('review_controls')
        )
        note = str(controls[0] or '').strip()
        override_suburb = str(controls[1] or '').strip().upper()
        override_state = str(controls[2] or '').strip().upper()
        override_postcode = str(controls[3] or '').strip()

        cleaned['review_controls'] = [
            note,
            override_suburb,
            override_state,
            override_postcode,
        ]

        matches = (self.instance.current_data or {}).get('historical_matches') or []
        matches_by_id = {
            int(match['id']): match
            for match in matches
            if match.get('id') is not None
        }

        raw_selected = cleaned.get('selected_historical_suburb_id')
        selected_id = None
        if raw_selected not in (None, ''):
            try:
                selected_id = int(raw_selected)
            except (TypeError, ValueError):
                raise forms.ValidationError(
                    'The selected Current DB row is invalid.'
                )

            if selected_id not in matches_by_id:
                raise forms.ValidationError(
                    'The selected Current DB row is no longer one of the current comparison candidates.'
                )

        decision = cleaned.get('decision')
        source_action = str(
            (self.instance.current_data or {}).get('source_action') or ''
        )

        if decision == 'ACCEPT_SOURCE':
            if source_action == 'REPLACE' and selected_id is None:
                raise forms.ValidationError(
                    'Select the Current DB row that this source row would replace.'
                )

        if decision == 'MANUAL_OVERRIDE':
            if not note:
                raise forms.ValidationError(
                    'Manual override requires a review note explaining why the authoritative source is being overridden.'
                )
            if not override_suburb or not override_state or not override_postcode:
                raise forms.ValidationError(
                    'Manual override requires final suburb, state and postcode.'
                )
            if source_action == 'REPLACE' and selected_id is None:
                raise forms.ValidationError(
                    'Select the Current DB row associated with this replacement before using Manual override.'
                )

        cleaned['selected_historical_suburb_id'] = selected_id
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        controls = self._normalise_controls(
            self.cleaned_data.get('review_controls')
        )
        note = str(controls[0] or '').strip()
        override_suburb = str(controls[1] or '').strip().upper()
        override_state = str(controls[2] or '').strip().upper()
        override_postcode = str(controls[3] or '').strip()

        instance.notes = note

        decision = self.cleaned_data.get('decision')
        source = instance.source_data or {}

        if decision == 'ACCEPT_SOURCE':
            instance.corrected_suburb = str(
                source.get('suburb') or ''
            ).strip().upper()
            instance.corrected_state = str(
                source.get('state') or ''
            ).strip().upper()
            instance.corrected_postcode = str(
                source.get('postcode') or ''
            ).strip()
        elif decision == 'MANUAL_OVERRIDE':
            instance.corrected_suburb = override_suburb
            instance.corrected_state = override_state
            instance.corrected_postcode = override_postcode
        else:
            # Preserve the existing final metadata while Pending/Needs review.
            # New review rows are already initialised from the source by sync.
            if not instance.corrected_suburb:
                instance.corrected_suburb = str(
                    source.get('suburb') or ''
                ).strip().upper()
            if not instance.corrected_state:
                instance.corrected_state = str(
                    source.get('state') or ''
                ).strip().upper()
            if not instance.corrected_postcode:
                instance.corrected_postcode = str(
                    source.get('postcode') or ''
                ).strip()

        if commit:
            instance.save()
        return instance

class ExternalDataReviewItemInline(admin.TabularInline):
    model = ExternalDataReviewItem
    form = PostcodesReviewItemForm
    extra = 0
    can_delete = False
    show_change_link = False
    verbose_name = 'Review item'
    verbose_name_plural = (
        'Postcodes Review - postcodes.csv is authoritative'
    )
    fields = (
        'source_display',
        'selected_historical_suburb_id',
        'source_action_display',
        'decision',
        'review_controls',
    )
    readonly_fields = (
        'source_display',
        'source_action_display',
    )

    class Media:
        css = {
            'all': ('admin/imports/postcodes_review_compact.css',)
        }
        js = ('admin/imports/postcodes_review_compact.js',)

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_current=True)

    @admin.display(description='Source')
    def source_display(self, obj):
        source = obj.source_data or {}
        return format_html(
            '<span class="postcodes-source-value">'
            '<strong>{}</strong> {} <code>{}</code>'
            '</span>',
            source.get('suburb') or '-',
            source.get('state') or '-',
            source.get('postcode') or '-',
        )

    @admin.display(description='Action')
    def source_action_display(self, obj):
        current_data = obj.current_data or {}
        action = str(current_data.get('source_action') or 'REVIEW').upper()
        reason = str(current_data.get('source_action_reason') or '')

        allowed = {'ADD', 'REPLACE', 'UNCHANGED', 'REVIEW', 'ALREADY_ADDED'}
        if action not in allowed:
            action = 'REVIEW'

        badge_text = 'ADDED' if action == 'ALREADY_ADDED' else action
        css_action = action.lower()
        return format_html(
            '<span class="postcodes-action-badge postcodes-action-{}" title="{}">{}</span>',
            css_action,
            reason,
            badge_text,
        )

@admin.register(ExternalDataFile)
class ExternalDataFileAdmin(FtpInboxAdminMixin, PostcodesApplyAdminMixin, admin.ModelAdmin):
    change_form_template = 'admin/imports/externaldatafile/change_form_with_postcodes_apply.html'
    form = ExternalDataFileAdminForm
    change_list_template = 'admin/imports/externaldatafile/change_list.html'
    list_display = (
        'client', 'file_type', 'original_filename', 'source_method', 'status',
        'uploaded_at', 'activated_at', 'operation_links',
    )
    list_filter = ('client', 'file_type', 'source_method', 'status')
    search_fields = ('original_filename', 'stored_path', 'sha256', 'source_url')
    date_hierarchy = 'uploaded_at'
    ordering = ('-uploaded_at',)


    def get_inlines(self, request, obj):
        if obj is not None and obj.file_type == 'SUBURBS':
            return [ExternalDataReviewItemInline]
        return []

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if object_id:
            external_file = self.get_object(request, object_id)
            if external_file is not None and external_file.file_type == 'SUBURBS':
                sync_postcodes_review_items(external_file)
        return super().changeform_view(
            request,
            object_id=object_id,
            form_url=form_url,
            extra_context=extra_context,
        )

    def save_formset(self, request, form, formset, change):
        if formset.model is ExternalDataReviewItem:
            changed_items = formset.save(commit=False)
            now = timezone.now()

            for item in changed_items:
                if item.decision == 'PENDING':
                    item.reviewed_by = None
                    item.reviewed_at = None
                else:
                    item.reviewed_by = request.user
                    item.reviewed_at = now
                item.save()

            formset.save_m2m()

            if changed_items:
                external_file = formset.instance
                decision_counts = {}
                for decision in ExternalDataReviewItem.objects.filter(
                    external_file=external_file,
                    is_current=True,
                ).values_list('decision', flat=True):
                    decision_counts[decision] = decision_counts.get(decision, 0) + 1

                create_audit_event(
                    event_type='EXTERNAL_DATA_REVIEW_UPDATED',
                    message=(
                        f'External data review updated for '
                        f'{external_file.client.code} {external_file.original_filename}.'
                    ),
                    actor=request.user,
                    client=external_file.client,
                    external_file=external_file,
                    metadata={
                        'file_type': external_file.file_type,
                        'decisions': decision_counts,
                        'operational_tables_updated': False,
                    },
                    request=request,
                )
            return

        return super().save_formset(request, form, formset, change)

    @staticmethod
    def _require_permission(request, permission):
        if not request.user.has_perm(permission):
            raise PermissionDenied(f'Missing permission: {permission}')

    def get_urls(self):
        custom_urls = [
            path(
                'fetch-fuel/',
                self.admin_site.admin_view(self.fetch_fuel_view),
                name='imports_externaldatafile_fetch_fuel',
            ),
            path(
                'upload-products/',
                self.admin_site.admin_view(self.upload_products_view),
                name='imports_externaldatafile_upload_products',
            ),
            path(
                'upload-stock/',
                self.admin_site.admin_view(self.upload_stock_view),
                name='imports_externaldatafile_upload_stock',
            ),
            path(
                '<int:object_id>/validate-source/',
                self.admin_site.admin_view(self.validate_reference_source_view),
                name='imports_externaldatafile_validate_source',
            ),
            path(
                '<int:object_id>/validate-fuel/',
                self.admin_site.admin_view(self.validate_fuel_view),
                name='imports_externaldatafile_validate_fuel',
            ),
            path(
                '<int:object_id>/activate-fuel/',
                self.admin_site.admin_view(self.activate_fuel_view),
                name='imports_externaldatafile_activate_fuel',
            ),
            path(
                '<int:object_id>/rollback-fuel/',
                self.admin_site.admin_view(self.rollback_fuel_view),
                name='imports_externaldatafile_rollback_fuel',
            ),
            path(
                '<int:object_id>/download/',
                self.admin_site.admin_view(self.download_view),
                name='imports_externaldatafile_download',
            ),
        ]
        return custom_urls + super().get_urls()

    def get_readonly_fields(self, request, obj=None):
        system_fields = (
            'source_method', 'source_url', 'original_filename', 'stored_path',
            'file_size_bytes', 'mime_type', 'sha256', 'uploaded_by', 'uploaded_at',
            'status', 'validation_summary_display', 'validated_by', 'validated_at',
            'import_summary_display', 'imported_by', 'last_imported_at',
            'activated_by', 'activated_at', 'rolled_back_by', 'rolled_back_at',
            'previous_active_file', 'error_message',
        )
        if obj is None:
            return system_fields
        return ('client', 'file_type', 'uploaded_file') + system_fields

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                ('Manual external source upload', {
                    'fields': ('client', 'file_type', 'uploaded_file', 'notes'),
                    'description': (
                        'Fuel accepts .csv. Product and stock reference sources accept .xlsx. '
                        'Product/stock uploads do not change operational data.'
                    ),
                }),
            )

        fieldsets = [
            ('File', {'fields': (
                'client', 'file_type', 'source_method', 'source_url', 'original_filename',
                'uploaded_file', 'stored_path', 'file_size_bytes', 'mime_type', 'sha256', 'notes',
            )}),
            ('Upload', {'fields': ('uploaded_by', 'uploaded_at', 'status')}),
            ('Validation', {'fields': (
                'validated_by', 'validated_at', 'validation_summary_display', 'error_message',
            )}),
        ]
        if obj.file_type in {'FUEL', 'SUBURBS'}:
            fieldsets.append(
                ('Activation and rollback', {'fields': (
                    'imported_by', 'last_imported_at', 'activated_by', 'activated_at',
                    'rolled_back_by', 'rolled_back_at', 'previous_active_file',
                    'import_summary_display',
                )})
            )
        return tuple(fieldsets)

    @staticmethod
    def _decimal_or_none(value):
        if value in (None, ''):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _normalise_summary_messages(values):
        messages_out = []
        for value in values or []:
            if isinstance(value, (dict, list)):
                messages_out.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
            else:
                messages_out.append(str(value))
        return messages_out

    @admin.display(description='Validation summary')
    def validation_summary_display(self, obj):
        summary = obj.validation_summary or {}
        if not summary:
            return format_html('<span class="help">No validation summary is available.</span>')

        if obj.file_type == 'FUEL':
            return self._fuel_validation_summary(obj, summary)
        if obj.file_type == 'SUBURBS':
            return self._postcodes_validation_summary(obj, summary)
        if obj.file_type in REFERENCE_FILE_TYPES:
            return self._reference_validation_summary(obj, summary)

        return format_html(
            '<pre style="white-space:pre-wrap">{}</pre>',
            json.dumps(summary, indent=2),
        )
    def _reference_validation_summary(self, obj, summary):
        errors = self._normalise_summary_messages(summary.get('errors'))
        warnings = self._normalise_summary_messages(summary.get('warnings'))
        rows_invalid = int(summary.get('rows_invalid') or 0)
        if errors or rows_invalid:
            status_label = 'Validation failed'
            status_class = 'sth-status-error'
        elif warnings:
            status_label = 'Validated with warnings'
            status_class = 'sth-status-warning'
        else:
            status_label = 'Validated'
            status_class = 'sth-status-success'

        sha256 = obj.sha256 or ''
        sha256_short = f'{sha256[:8]}…{sha256[-6:]}' if len(sha256) > 16 else (sha256 or '—')
        context = {
            'summary': summary,
            'status_label': status_label,
            'status_class': status_class,
            'source_label': 'PRODUCT SOURCE' if obj.file_type == 'PRODUCTS' else 'STOCK SOURCE',
            'file_type': obj.file_type,
            'preview_rows': summary.get('preview') or [],
            'warnings': warnings,
            'errors': errors,
            'sha256': sha256,
            'sha256_short': sha256_short,
            'original_filename': obj.original_filename or '—',
            'source_method': obj.source_method or '—',
            'uploaded_by': obj.uploaded_by,
            'uploaded_at': obj.uploaded_at,
            'raw_json': json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        }
        return mark_safe(render_to_string(
            'admin/imports/externaldatafile/reference_validation_summary.html',
            context,
        ))

    def _postcodes_validation_summary(self, obj, summary):
        errors = self._normalise_summary_messages(summary.get('errors'))
        warnings = self._normalise_summary_messages(summary.get('warnings'))

        new_rows = (
            summary.get('new_rows_preview')
            or summary.get('would_add_preview')
            or []
        )
        excluded_rows = summary.get('excluded_rows') or []

        if errors:
            status_label = 'Validation failed'
            status_class = 'sth-status-error'
        elif warnings:
            status_label = 'Validated with warnings'
            status_class = 'sth-status-warning'
        else:
            status_label = 'Validated'
            status_class = 'sth-status-success'

        possible_alias_count = sum(
            1 for row in new_rows if row.get('possible_alias')
        )

        sha256 = obj.sha256 or ''
        sha256_short = (
            f'{sha256[:8]}...{sha256[-6:]}'
            if len(sha256) > 16
            else (sha256 or '-')
        )

        import_summary = obj.import_summary or {}

        context = {
            'summary': summary,
            'status_label': status_label,
            'status_class': status_class,
            'source_format': summary.get('source_format') or 'FTP_POSTCODES',
            'rows_read': int(summary.get('rows_read') or 0),
            'candidate_rows': int(summary.get('candidate_rows') or 0),
            'existing_confirmed': int(
                summary.get('existing_confirmed_in_current_source') or 0
            ),
            'new_rows_count': int(
                summary.get('new_rows_to_add') or len(new_rows) or 0
            ),
            'existing_preserved': int(
                summary.get('existing_not_in_current_source_preserved') or 0
            ),
            'excluded_rows_count': int(
                summary.get('excluded_rows_count') or len(excluded_rows) or 0
            ),
            'possible_alias_count': possible_alias_count,
            'multi_postcode_groups': int(
                summary.get('multi_postcode_suburb_state_groups') or 0
            ),
            'new_rows': new_rows,
            'excluded_rows': excluded_rows,
            'warnings': warnings,
            'errors': errors,
            'activation_policy': summary.get('activation_policy') or '-',
            'existing_action': summary.get('existing_action') or '-',
            'new_action': summary.get('new_action') or '-',
            'not_in_source_action': summary.get('not_in_source_action') or '-',
            'freightzone_required_for_add': bool(
                summary.get('freightzone_required_for_add')
            ),
            'sha256': sha256,
            'sha256_short': sha256_short,
            'original_filename': obj.original_filename or '-',
            'source_method': obj.source_method or '-',
            'raw_json': json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            'import_summary': import_summary,
            'created_count': int(import_summary.get('created_count') or 0),
            'updated_count': int(import_summary.get('updated_count') or 0),
            'deleted_count': int(import_summary.get('deleted_count') or 0),
            'renamed_count': int(import_summary.get('renamed_count') or 0),
            'import_activation_policy': (
                import_summary.get('activation_policy') or '-'
            ),
            'created_rows_origin': import_summary.get('created_rows_origin') or '',
            'raw_import_json': json.dumps(
                import_summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        }

        return mark_safe(render_to_string(
            'admin/imports/externaldatafile/postcodes_validation_summary.html',
            context,
        ))
    def _fuel_validation_summary(self, obj, summary):
        preview_rows = []
        for item in summary.get('preview') or []:
            current_rate = self._decimal_or_none(item.get('current_rate'))
            new_rate = self._decimal_or_none(item.get('new_rate'))
            difference = None
            if current_rate is not None and new_rate is not None:
                difference = (new_rate - current_rate) * Decimal('100')

            result = str(item.get('result') or '').upper()
            preview_rows.append({
                'carrier': item.get('carrier') or '-',
                'service': item.get('service') or '-',
                'ratecard': item.get('ratecard') or '-',
                'config_id': item.get('config_id') or '-',
                'current_rate_display': (
                    f'{current_rate * 100:.2f}%' if current_rate is not None else '—'
                ),
                'new_rate_display': (
                    f'{new_rate * 100:.2f}%' if new_rate is not None else '—'
                ),
                'difference_display': (
                    f'{difference:+.2f} pp' if difference is not None else '—'
                ),
                'result': result,
                'result_label': {
                    'CHANGE': 'Change',
                    'UNCHANGED': 'Unchanged',
                }.get(result, result.title() or 'Unknown'),
                'result_class': {
                    'CHANGE': 'sth-result-change',
                    'UNCHANGED': 'sth-result-unchanged',
                }.get(result, 'sth-result-info'),
            })

        errors = self._normalise_summary_messages(summary.get('errors'))
        warnings = self._normalise_summary_messages(summary.get('warnings'))
        rows_invalid = int(summary.get('rows_invalid') or 0)
        is_expired = bool(summary.get('is_expired'))

        if errors or rows_invalid:
            status_label = 'Validation failed'
            status_class = 'sth-status-error'
        elif is_expired:
            status_label = 'Validated — expired'
            status_class = 'sth-status-warning'
        elif warnings:
            status_label = 'Validated with warnings'
            status_class = 'sth-status-warning'
        else:
            status_label = 'Validated'
            status_class = 'sth-status-success'

        change_rows = [row for row in preview_rows if row['result'] == 'CHANGE']
        unchanged_rows = [row for row in preview_rows if row['result'] == 'UNCHANGED']
        sha256 = obj.sha256 or ''
        sha256_short = f'{sha256[:8]}…{sha256[-6:]}' if len(sha256) > 16 else (sha256 or '—')

        context = {
            'summary': summary,
            'status_label': status_label,
            'status_class': status_class,
            'change_rows': change_rows,
            'unchanged_rows': unchanged_rows,
            'warnings': warnings,
            'errors': errors,
            'ratecards_matched': summary.get('ratecards_matched') or [],
            'ratecards_not_found': summary.get('ratecards_not_found_in_django') or [],
            'django_ratecards_missing': summary.get('django_ratecards_missing_from_file') or [],
            'sha256': sha256,
            'sha256_short': sha256_short,
            'original_filename': obj.original_filename or '—',
            'source_method': obj.source_method or '—',
            'source_url': obj.source_url or '—',
            'uploaded_by': obj.uploaded_by,
            'uploaded_at': obj.uploaded_at,
            'raw_json': json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        }
        return mark_safe(render_to_string(
            'admin/imports/externaldatafile/validation_summary.html',
            context,
        ))

    @admin.display(description='Import summary')
    def import_summary_display(self, obj):
        summary = obj.import_summary or {}
        if not summary:
            return format_html('<span class="help">No import summary is available.</span>')

        if obj.file_type == 'SUBURBS':
            return format_html(
                '<table style="border-collapse:collapse">'
                '<tr><th style="text-align:left;padding:4px 12px 4px 0">Created</th><td>{}</td></tr>'
                '<tr><th style="text-align:left;padding:4px 12px 4px 0">Updated</th><td>{}</td></tr>'
                '<tr><th style="text-align:left;padding:4px 12px 4px 0">Deleted</th><td>{}</td></tr>'
                '<tr><th style="text-align:left;padding:4px 12px 4px 0">Renamed</th><td>{}</td></tr>'
                '<tr><th style="text-align:left;padding:4px 12px 4px 0">Policy</th><td><code>{}</code></td></tr>'
                '<tr><th style="text-align:left;padding:4px 12px 4px 0">Created row origin</th><td><code>{}</code></td></tr>'
                '</table>',
                summary.get('created_count', 0),
                summary.get('updated_count', 0),
                summary.get('deleted_count', 0),
                summary.get('renamed_count', 0),
                summary.get('activation_policy', '-'),
                summary.get('created_rows_origin', '-'),
            )

        return format_html(
            '<pre style="white-space:pre-wrap">{}</pre>',
            json.dumps(summary, indent=2),
        )
    @admin.display(description='Operations')
    def operation_links(self, obj):
        links = []
        if obj.uploaded_file or obj.stored_path:
            links.append(format_html(
                '<a href="{}">Download</a>',
                reverse('admin:imports_externaldatafile_download', args=[obj.pk]),
            ))

        if obj.file_type == 'FUEL':
            if obj.status in {'UPLOADED', 'DOWNLOADED', 'VALIDATED', 'VALIDATION_FAILED', 'IMPORT_FAILED'}:
                links.append(format_html(
                    '<a href="{}">Validate</a>',
                    reverse('admin:imports_externaldatafile_validate_fuel', args=[obj.pk]),
                ))
            if obj.status == 'VALIDATED':
                links.append(format_html(
                    '<a href="{}">Activate</a>',
                    reverse('admin:imports_externaldatafile_activate_fuel', args=[obj.pk]),
                ))
            if obj.status == 'ACTIVE':
                links.append(format_html(
                    '<a href="{}">Rollback</a>',
                    reverse('admin:imports_externaldatafile_rollback_fuel', args=[obj.pk]),
                ))
        elif obj.file_type in REFERENCE_FILE_TYPES:
            if obj.status in {'UPLOADED', 'VALIDATED', 'VALIDATION_FAILED', 'IMPORT_FAILED'}:
                links.append(format_html(
                    '<a href="{}">Validate</a>',
                    reverse('admin:imports_externaldatafile_validate_source', args=[obj.pk]),
                ))
            if obj.status == 'VALIDATED':
                if obj.file_type == 'PRODUCTS':
                    row_url = reverse('admin:imports_productsourcerow_changelist')
                else:
                    row_url = reverse('admin:imports_stocksourcerow_changelist')
                row_url = f'{row_url}?{urlencode({"external_file__id__exact": obj.pk})}'
                links.append(format_html('<a href="{}">View rows</a>', row_url))

        return format_html(' &nbsp;|&nbsp; '.join('{}' for _ in links), *links) if links else '-'

    def save_model(self, request, obj, form, change):
        if not change:
            uploaded = form.cleaned_data['uploaded_file']
            uploaded.seek(0)
            content = uploaded.read()
            uploaded.seek(0)
            obj.source_method = 'ADMIN_UPLOAD'
            obj.source_url = ''
            obj.original_filename = Path(uploaded.name).name
            obj.file_size_bytes = len(content)
            fallback_type = 'text/csv' if obj.file_type == 'FUEL' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            obj.mime_type = (
                getattr(uploaded, 'content_type', '')
                or mimetypes.guess_type(uploaded.name)[0]
                or fallback_type
            )
            obj.sha256 = calculate_sha256(content)
            obj.uploaded_by = request.user
            obj.status = 'UPLOADED'
        super().save_model(request, obj, form, change)
        if not change:
            obj.stored_path = obj.uploaded_file.name
            obj.save(update_fields=['stored_path'])
            event_type = {
                'FUEL': 'FUEL_FILE_UPLOADED',
                'PRODUCTS': 'PRODUCT_SOURCE_UPLOADED',
                'STOCK': 'STOCK_SOURCE_UPLOADED',
            }.get(obj.file_type, 'EXTERNAL_FILE_UPLOADED')
            create_audit_event(
                event_type=event_type,
                message=f'{obj.get_file_type_display()} file uploaded for {obj.client.code}.',
                actor=request.user,
                client=obj.client,
                external_file=obj,
                metadata={
                    'source_method': obj.source_method,
                    'original_filename': obj.original_filename,
                    'stored_filename': obj.uploaded_file.name,
                    'file_size_bytes': obj.file_size_bytes,
                    'mime_type': obj.mime_type,
                    'sha256': obj.sha256,
                    'operational_tables_updated': False if obj.file_type in REFERENCE_FILE_TYPES else None,
                },
                request=request,
            )

    def has_delete_permission(self, request, obj=None):
        # Import files form part of the audit trail and should be archived, not deleted.
        return False

    def upload_products_view(self, request):
        return self._source_upload_view(
            request,
            file_type='PRODUCTS',
            title='Upload product_sth.xlsx',
            expected_filename='product_sth.xlsx',
        )

    def upload_stock_view(self, request):
        return self._source_upload_view(
            request,
            file_type='STOCK',
            title='Upload stock_sth.xlsx',
            expected_filename='stock_sth.xlsx',
        )

    def _source_upload_view(self, request, *, file_type, title, expected_filename):
        if not self.has_add_permission(request):
            raise Http404
        form = SourceUploadForm(
            request.POST or None,
            request.FILES or None,
            expected_filename=expected_filename,
        )
        if request.method == 'POST' and form.is_valid():
            uploaded = form.cleaned_data['uploaded_file']
            uploaded.seek(0)
            content = uploaded.read()
            uploaded.seek(0)
            filename = Path(uploaded.name).name
            external_file = ExternalDataFile(
                client=form.cleaned_data['client'],
                file_type=file_type,
                source_method='ADMIN_UPLOAD',
                source_url='',
                original_filename=filename,
                file_size_bytes=len(content),
                mime_type=(
                    getattr(uploaded, 'content_type', '')
                    or mimetypes.guess_type(filename)[0]
                    or 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                ),
                sha256=calculate_sha256(content),
                notes=form.cleaned_data['notes'],
                uploaded_by=request.user,
                status='UPLOADED',
            )
            external_file.uploaded_file.save(filename, ContentFile(content), save=False)
            external_file.save()
            external_file.stored_path = external_file.uploaded_file.name
            external_file.save(update_fields=['stored_path'])

            create_audit_event(
                event_type=(
                    'PRODUCT_SOURCE_UPLOADED' if file_type == 'PRODUCTS'
                    else 'STOCK_SOURCE_UPLOADED'
                ),
                message=f'{expected_filename} uploaded for {external_file.client.code}.',
                actor=request.user,
                client=external_file.client,
                external_file=external_file,
                metadata={
                    'source_method': external_file.source_method,
                    'original_filename': filename,
                    'stored_filename': external_file.uploaded_file.name,
                    'file_size_bytes': len(content),
                    'mime_type': external_file.mime_type,
                    'sha256': external_file.sha256,
                    'operational_tables_updated': False,
                },
                request=request,
            )

            try:
                summary = self._validate_reference_source(
                    external_file,
                    actor=request.user,
                    request=request,
                )
                self.message_user(
                    request,
                    f'Reference source validated: {summary["rows_valid"]} rows stored. '
                    'No operational data was modified.',
                    messages.SUCCESS,
                )
            except SourceImportError as exc:
                self.message_user(request, str(exc), messages.ERROR)
            return redirect(
                reverse('admin:imports_externaldatafile_change', args=[external_file.pk])
            )

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': title,
            'form': form,
            'expected_filename': expected_filename,
        }
        return TemplateResponse(
            request,
            'admin/imports/externaldatafile/upload_source.html',
            context,
        )

    @staticmethod
    def _validate_reference_source(obj, *, actor=None, request=None):
        if obj.file_type == 'PRODUCTS':
            return validate_product_source_file(obj, actor=actor, request=request)
        if obj.file_type == 'STOCK':
            return validate_stock_source_file(obj, actor=actor, request=request)
        raise SourceImportError('This file is not a product or stock reference source.')

    def validate_reference_source_view(self, request, object_id):
        self._require_permission(request, 'imports.validate_external_data_file')
        obj = get_object_or_404(
            ExternalDataFile,
            pk=object_id,
            file_type__in=REFERENCE_FILE_TYPES,
        )
        if request.method == 'POST':
            try:
                summary = self._validate_reference_source(
                    obj,
                    actor=request.user,
                    request=request,
                )
                self.message_user(
                    request,
                    f'Reference validation passed: {summary["rows_valid"]} rows stored. '
                    'No operational data was modified.',
                    messages.SUCCESS,
                )
            except SourceImportError as exc:
                self.message_user(request, str(exc), messages.ERROR)
            return redirect(reverse('admin:imports_externaldatafile_change', args=[obj.pk]))
        return self._action_confirmation(
            request,
            obj,
            title=f'Validate {obj.get_file_type_display()} reference source',
            action_label='Validate',
            explanation=(
                'This reads the workbook into isolated staging tables. '
                'It does not update Product, FreightRate, FreightZone, carrier configuration, '
                'fuel values or the calculator.'
            ),
        )

    def fetch_fuel_view(self, request):
        if not self.has_add_permission(request):
            raise Http404
        active_clients = list(Client.objects.filter(active=True).order_by('code'))
        source_urls_by_client = {
            str(client.pk): remembered_fuel_source_url(client)
            for client in active_clients
        }
        initial_client = next(
            (client for client in active_clients if client.code.upper() == 'STH'),
            active_clients[0] if active_clients else None,
        )
        initial_source_url = (
            source_urls_by_client.get(str(initial_client.pk), default_fuel_source_url())
            if initial_client else default_fuel_source_url()
        )
        form = FetchFuelForm(
            request.POST or None,
            initial={
                'client': initial_client,
                'source_url': initial_source_url,
            },
        )
        if request.method == 'POST' and form.is_valid():
            try:
                external_file = create_downloaded_fuel_file(
                    client=form.cleaned_data['client'],
                    actor=request.user,
                    source_url=form.cleaned_data['source_url'],
                    notes=form.cleaned_data['notes'],
                    request=request,
                )
                validate_fuel_file(external_file, actor=request.user, request=request)
                self.message_user(
                    request,
                    'Fuel file downloaded and validated. Review the preview before activation.',
                    messages.SUCCESS,
                )
                return redirect(
                    reverse('admin:imports_externaldatafile_change', args=[external_file.pk])
                )
            except FuelImportError as exc:
                self.message_user(request, str(exc), messages.ERROR)
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Fetch fuel from source',
            'form': form,
            'source_urls_by_client': source_urls_by_client,
        }
        return TemplateResponse(request, 'admin/imports/externaldatafile/fetch_fuel.html', context)

    def validate_fuel_view(self, request, object_id):
        self._require_permission(request, 'imports.validate_external_data_file')
        obj = get_object_or_404(ExternalDataFile, pk=object_id, file_type='FUEL')
        if request.method == 'POST':
            try:
                summary = validate_fuel_file(obj, actor=request.user, request=request)
                self.message_user(
                    request,
                    f'Fuel validation passed: {summary["rows_valid"]} rows; '
                    f'{summary["configs_to_update"]} configurations would change.',
                    messages.SUCCESS,
                )
            except FuelImportError as exc:
                self.message_user(request, str(exc), messages.ERROR)
            return redirect(reverse('admin:imports_externaldatafile_change', args=[obj.pk]))
        return self._action_confirmation(
            request,
            obj,
            title='Validate fuel file',
            action_label='Validate',
            explanation='Validation does not change carrier fuel rates.',
        )

    def activate_fuel_view(self, request, object_id):
        self._require_permission(request, 'imports.activate_fuel')
        obj = get_object_or_404(ExternalDataFile, pk=object_id, file_type='FUEL')
        form = FuelActivationForm(request.POST or None, user=request.user)
        if request.method == 'POST' and form.is_valid():
            try:
                summary = activate_fuel_file(
                    obj,
                    actor=request.user,
                    request=request,
                    force_expired=form.cleaned_data['force_expired'],
                    justification=form.cleaned_data['justification'],
                )
                self.message_user(
                    request,
                    f'Fuel rates activated: {summary["configs_updated"]} changed and '
                    f'{summary["configs_unchanged"]} unchanged.',
                    messages.SUCCESS,
                )
                return redirect(reverse('admin:imports_externaldatafile_change', args=[obj.pk]))
            except FuelImportError as exc:
                self.message_user(request, str(exc), messages.ERROR)
        return self._action_confirmation(
            request,
            obj,
            title='Activate fuel rates',
            action_label='Activate',
            explanation='This updates Client carrier configs using master_rate → ratecard.',
            form=form,
        )

    def rollback_fuel_view(self, request, object_id):
        self._require_permission(request, 'imports.rollback_fuel')
        obj = get_object_or_404(ExternalDataFile, pk=object_id, file_type='FUEL')
        form = FuelRollbackForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            try:
                summary = rollback_fuel_file(
                    obj,
                    actor=request.user,
                    request=request,
                    reason=form.cleaned_data['reason'],
                )
                self.message_user(
                    request,
                    f'Fuel rollback completed: {summary["configs_restored"]} configurations restored.',
                    messages.WARNING,
                )
                return redirect(reverse('admin:imports_externaldatafile_change', args=[obj.pk]))
            except FuelImportError as exc:
                self.message_user(request, str(exc), messages.ERROR)
        return self._action_confirmation(
            request,
            obj,
            title='Rollback active fuel rates',
            action_label='Rollback',
            explanation='This restores the values recorded immediately before this activation.',
            form=form,
        )

    def _action_confirmation(self, request, obj, *, title, action_label, explanation, form=None):
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': title,
            'action_label': action_label,
            'explanation': explanation,
            'object': obj,
            'form': form,
            'back_url': reverse('admin:imports_externaldatafile_change', args=[obj.pk]),
        }
        return TemplateResponse(request, 'admin/imports/externaldatafile/fuel_action.html', context)

    def download_view(self, request, object_id):
        self._require_permission(request, 'imports.download_external_data_file')
        obj = get_object_or_404(ExternalDataFile, pk=object_id)
        if obj.uploaded_file:
            try:
                obj.uploaded_file.open('rb')
                return FileResponse(
                    obj.uploaded_file,
                    as_attachment=True,
                    filename=obj.original_filename,
                    content_type=obj.mime_type or 'application/octet-stream',
                )
            except (FileNotFoundError, ValueError) as exc:
                raise Http404('Stored file not found.') from exc
        if obj.stored_path and Path(obj.stored_path).is_file():
            return FileResponse(
                open(obj.stored_path, 'rb'),
                as_attachment=True,
                filename=obj.original_filename,
                content_type=obj.mime_type or 'application/octet-stream',
            )
        raise Http404('Stored file not found.')


class ReadOnlySourceRowAdmin(admin.ModelAdmin):
    list_per_page = 100
    show_full_result_count = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj)


@admin.register(ProductSourceRow)
class ProductSourceRowAdmin(ReadOnlySourceRowAdmin):
    list_display = (
        'external_file', 'source_row_number', 'product_code_normalized', 'name',
        'category', 'weight_kg', 'cubic_m3', 'source_status',
    )
    list_filter = ('external_file__client', 'external_file', 'category', 'source_status')
    search_fields = ('product_code_normalized', 'product_code_raw', 'name', 'description')
    list_select_related = ('external_file', 'external_file__client')
    ordering = ('external_file', 'source_row_number')


@admin.register(StockSourceRow)
class StockSourceRowAdmin(ReadOnlySourceRowAdmin):
    list_display = (
        'external_file', 'source_row_number', 'product_code_normalized', 'sql_name',
        'quantity', 'pallet', 'weight_kg', 'cubic_m3', 'location', 'source_status',
    )
    list_filter = ('external_file__client', 'external_file', 'location', 'source_status')
    search_fields = (
        'product_code_normalized', 'product_code_raw', 'sql_name', 'serial_no', 'movement_number',
    )
    list_select_related = ('external_file', 'external_file__client')
    ordering = ('external_file', 'source_row_number')

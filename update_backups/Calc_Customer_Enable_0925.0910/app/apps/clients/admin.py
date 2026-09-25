"""Customer master and Calculator Customer administration."""

import hashlib
import logging
import tempfile
import uuid
from pathlib import Path

from django import forms
from django.contrib import admin, messages
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from apps.authentication_gateway.services import is_django_administrator

from .customer_import import (
    MAX_UPLOAD_BYTES, CustomerImportError, import_customers,
    master_state_digest, preview_customers,
)
from .models import Client, Customer, CustomerImport


logger = logging.getLogger(__name__)


class CustomerUploadForm(forms.Form):
    file = forms.FileField(label='Customer workbook (.xls)')

    def clean_file(self):
        upload = self.cleaned_data['file']
        if Path(upload.name).suffix.lower() != '.xls' or upload.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError('Select a legacy .xls workbook of no more than 5 MB.')
        return upload


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'active', 'translogic_link', 'updated_at')
    search_fields = ('code', 'name')

    @admin.display(description='Translogic Customer')
    def translogic_link(self, obj):
        try:
            return obj.translogic_customer.code
        except Customer.DoesNotExist:
            return '—'


class LinkedFilter(admin.SimpleListFilter):
    title = 'Calculator Customer link'
    parameter_name = 'linked'

    def lookups(self, request, model_admin):
        return (('yes', 'Linked'), ('no', 'Unlinked'))

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(linked_client__isnull=False)
        if self.value() == 'no':
            return queryset.filter(linked_client__isnull=True)
        return queryset


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    change_list_template = 'admin/clients/customer/change_list.html'
    list_display = ('code', 'name', 'group', 'group1', 'group2', 'wh_pick_code',
                    'source_date', 'linked_client', 'is_special')
    search_fields = ('code', 'name', 'group', 'group1', 'group2')
    list_filter = ('group', 'group1', 'group2', 'is_special', LinkedFilter)
    list_select_related = ('linked_client',)
    readonly_fields = ('code', 'name', 'group', 'group1', 'group2', 'their_code',
                       'wh_pick_code', 'acn', 'abn', 'gst_code', 'sett_days',
                       'paydays_type', 'source_date', 'source_user', 'is_special',
                       'source_row_number', 'raw_data', 'created_at', 'updated_at')
    fields = readonly_fields + ('linked_client',)

    def has_module_permission(self, request):
        return is_django_administrator(request.user)

    def has_view_permission(self, request, obj=None):
        return is_django_administrator(request.user)

    def has_change_permission(self, request, obj=None):
        return is_django_administrator(request.user)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'linked_client':
            kwargs['queryset'] = Client.objects.filter(active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_urls(self):
        return [path('import/', self.admin_site.admin_view(self.import_view),
                     name='clients_customer_import')] + super().get_urls()

    def import_view(self, request):
        if not is_django_administrator(request.user):
            raise PermissionDenied('Customer imports require an administrator.')
        preview, token, error, filename = None, None, None, None
        form = CustomerUploadForm()
        if request.method == 'POST' and request.POST.get('action') == 'validate':
            form = CustomerUploadForm(request.POST, request.FILES)
            if form.is_valid():
                upload = form.cleaned_data['file']
                filename = Path(upload.name).name
                content = upload.read()
                try:
                    preview = preview_customers(content)
                    directory = Path(tempfile.gettempdir()) / 'calculator_customer_previews'
                    directory.mkdir(mode=0o700, exist_ok=True)
                    name = f'{uuid.uuid4().hex}.xls'
                    (directory / name).write_bytes(content)
                    token = signing.dumps({
                        'file': name, 'filename': filename,
                        'user': request.user.pk, 'sha256': hashlib.sha256(content).hexdigest(),
                        'state': master_state_digest(),
                    }, salt='customer-import-preview')
                    logger.info('Customer XLS validated: user=%s filename=%s sha256=%s rows=%s invalid=%s duplicates=%s',
                                request.user.pk, filename, hashlib.sha256(content).hexdigest(),
                                preview.total_rows, len(preview.errors), len(preview.duplicates))
                except CustomerImportError as exc:
                    error = str(exc)
                    logger.warning('Customer XLS validation failed: user=%s filename=%s reason=%s',
                                   request.user.pk, filename, error)
        elif request.method == 'POST' and request.POST.get('action') == 'import':
            try:
                payload = signing.loads(request.POST.get('token', ''),
                                        salt='customer-import-preview', max_age=1800)
                if payload['user'] != request.user.pk:
                    raise CustomerImportError('This preview belongs to another user.')
                name = payload['file']
                if Path(name).name != name or not name.endswith('.xls'):
                    raise CustomerImportError('Invalid preview reference.')
                source = Path(tempfile.gettempdir()) / 'calculator_customer_previews' / name
                content = source.read_bytes()
                history = import_customers(
                    content, filename=payload['filename'], actor=request.user,
                    expected_digest=payload['sha256'], expected_state=payload['state'],
                    request=request,
                )
                source.unlink(missing_ok=True)
                self.message_user(request, f'Imported {history.created_count} new and '
                                  f'{history.updated_count} changed Customers.', messages.SUCCESS)
                return HttpResponseRedirect(reverse('admin:clients_customer_changelist'))
            except (CustomerImportError, signing.BadSignature, KeyError, OSError) as exc:
                error = str(exc)
        context = {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Import Customers', 'form': form, 'preview': preview,
            'token': token, 'error': error, 'filename': filename,
        }
        return TemplateResponse(request, 'admin/clients/customer/import.html', context)


@admin.register(CustomerImport)
class CustomerImportAdmin(admin.ModelAdmin):
    list_display = ('filename', 'uploaded_at', 'uploaded_by', 'total_rows',
                    'created_count', 'updated_count', 'unchanged_count', 'missing_count', 'status')
    readonly_fields = ('filename', 'source_file', 'sha256', 'uploaded_at',
                       'uploaded_by', 'total_rows', 'created_count', 'updated_count',
                       'unchanged_count', 'missing_count', 'invalid_count',
                       'duplicate_count', 'special_count', 'status', 'details')
    fields = readonly_fields

    def has_module_permission(self, request):
        return is_django_administrator(request.user)

    def has_view_permission(self, request, obj=None):
        return is_django_administrator(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

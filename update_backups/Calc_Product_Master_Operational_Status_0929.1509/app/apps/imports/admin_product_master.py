"""Separate Admin upload and preview for the global Product Master."""

from hashlib import sha256
from pathlib import Path

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from apps.authentication_gateway.services import is_django_administrator
from apps.clients.models import Customer
from apps.imports.admin_reconciliation import ProductMasterReadOnlyReconciliation
from apps.imports.models import ProductMaster
from apps.imports.services.audit import create_audit_event
from apps.imports.services.product_master import validate_product_master
from apps.imports.services.xlsx_reader import SourceImportError


class ProductMasterUploadForm(forms.Form):
    original_file = forms.FileField(label='products.xls')

    def clean_original_file(self):
        upload = self.cleaned_data['original_file']
        if Path(upload.name).name.lower() != 'products.xls':
            raise forms.ValidationError('Select the products.xls workbook.')
        if upload.size == 0 or upload.size > 64 * 1024 * 1024:
            raise forms.ValidationError('The workbook must be between 1 byte and 64 MB.')
        return upload


@admin.register(ProductMaster)
class ProductMasterAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'status', 'uploaded_at', 'uploaded_by', 'sha256')
    ordering = ('-uploaded_at',)
    search_fields = ('original_filename', 'sha256')
    list_filter = ('status',)

    def has_module_permission(self, request):
        return is_django_administrator(request.user)

    def has_view_permission(self, request, obj=None):
        return is_django_administrator(request.user)

    def has_add_permission(self, request):
        return is_django_administrator(request.user)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path('<int:master_id>/compare/<int:client_id>/',
                 self.admin_site.admin_view(self.compare_view),
                 name='imports_productmaster_compare'),
            path('<int:master_id>/validate/', self.admin_site.admin_view(self.validate_view),
                 name='imports_productmaster_validate'),
        ] + super().get_urls()

    def add_view(self, request, form_url='', extra_context=None):
        if not self.has_add_permission(request):
            raise PermissionDenied('Product Master upload requires a Django administrator.')
        form = ProductMasterUploadForm(request.POST or None, request.FILES or None)
        if request.method == 'POST' and form.is_valid():
            upload = form.cleaned_data['original_file']
            content = upload.read()
            master = ProductMaster(
                original_filename=Path(upload.name).name,
                sha256=sha256(content).hexdigest(), file_size_bytes=len(content),
                uploaded_by=request.user,
            )
            master.original_file.save(master.original_filename, ContentFile(content), save=False)
            master.save()
            create_audit_event(
                event_type='PRODUCT_MASTER_UPLOADED',
                message=f'Global Product Master #{master.pk} uploaded.',
                actor=request.user,
                metadata={'product_master_id': master.pk, 'sha256': master.sha256,
                          'filename': master.original_filename, 'operational_tables_updated': False},
                request=request,
            )
            return redirect(reverse('admin:imports_productmaster_change', args=[master.pk]))
        return TemplateResponse(request, 'admin/imports/productmaster/upload.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Upload Product Master', 'form': form,
        })

    def change_view(self, request, object_id, form_url='', extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied('Product Master preview requires a Django administrator.')
        master = get_object_or_404(self.get_queryset(request), pk=object_id)
        linked = (
            Customer.objects.filter(
                code__in=(master.validation_summary or {}).get('customer_counts', {}),
                linked_client__isnull=False, is_special=False,
            ).select_related('linked_client').order_by('code')
            if master.status == 'VALIDATED' else []
        )
        return TemplateResponse(request, 'admin/imports/productmaster/preview.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Product Master', 'master': master,
            'summary': master.validation_summary or {},
            'linked_customers': linked,
        })

    def compare_view(self, request, master_id, client_id):
        # ProductMasterReadOnlyReconciliation applies the existing Client scope
        # before loading any global workbook rows, including for direct URLs.
        return ProductMasterReadOnlyReconciliation(self.admin_site)(
            request, master_id, client_id,
        )

    def validate_view(self, request, master_id):
        if not self.has_view_permission(request):
            raise PermissionDenied('Product Master validation requires a Django administrator.')
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        master = get_object_or_404(self.get_queryset(request), pk=master_id)
        try:
            master = validate_product_master(master.pk, actor=request.user)
            create_audit_event(
                event_type='PRODUCT_MASTER_VALIDATED',
                message=f'Global Product Master #{master.pk}: {master.status}.',
                actor=request.user,
                metadata={'product_master_id': master.pk, 'sha256': master.sha256,
                          'status': master.status, 'summary': {
                              key: value for key, value in master.validation_summary.items()
                              if key not in {'preview', 'customer_counts'}
                          }, 'operational_tables_updated': False},
                request=request,
            )
            if master.status == 'VALIDATION_FAILED':
                self.message_user(request, master.error_message, messages.ERROR)
            else:
                self.message_user(request, 'Product Master validated. No operational data changed.', messages.SUCCESS)
        except SourceImportError as exc:
            self.message_user(request, str(exc), messages.ERROR)
        return redirect(reverse('admin:imports_productmaster_change', args=[master.pk]))

from __future__ import annotations

from abc import ABC, abstractmethod

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse

from apps.imports.models import ExternalDataFile
from apps.imports.services.product_reconciliation import build_product_reconciliation


class ReadOnlyReconciliationWorkflow(ABC):
    """Reusable, paginated comparison workflow with no Apply operation."""

    template_name = 'admin/imports/reconciliation.html'
    page_title = ''
    page_description = ''
    page_size = 100

    def __init__(self, admin_site):
        self.admin_site = admin_site

    @abstractmethod
    def get_source(self, object_id):
        raise NotImplementedError

    @abstractmethod
    def build_reconciliation(self, source):
        raise NotImplementedError

    def has_permission(self, request):
        return request.user.is_active and request.user.is_staff and (
            request.user.is_superuser
            or request.user.has_perm('imports.view_productsourcerow')
        )

    def __call__(self, request, object_id):
        if not self.has_permission(request):
            raise PermissionDenied
        source = self.get_source(object_id)
        rows, summary = self.build_reconciliation(source)
        search = str(request.GET.get('q') or '').strip().lower()
        status = str(request.GET.get('status') or 'NEEDS_REVIEW').upper()

        filtered = rows
        if status == 'NEEDS_REVIEW':
            filtered = [row for row in filtered if row['status'] != 'SAME']
            priority = {
                'DIFFERENT': 0,
                'DUPLICATE_SOURCE': 1,
                'OPERATIONAL_ONLY': 2,
                'SOURCE_ONLY': 3,
            }
            filtered.sort(key=lambda row: (
                priority.get(row['status'], 9),
                row['sku'],
                row['source_row_number'] or 0,
            ))
        elif status and status != 'ALL':
            filtered = [row for row in filtered if row['status'] == status]
        if search:
            filtered = [
                row for row in filtered
                if search in row['sku'].lower()
                or search in str(row['source_values'].get('name') or '').lower()
                or search in str(row['operational_values'].get('name') or '').lower()
            ]

        page = Paginator(filtered, self.page_size).get_page(request.GET.get('page'))
        context = {
            **self.admin_site.each_context(request),
            'title': self.page_title,
            'page_description': self.page_description,
            'source': source,
            'summary': summary,
            'page_obj': page,
            'search': search,
            'selected_status': status,
            'result_count': len(filtered),
            'blocked': summary['pending_rejected'] > 0,
            'back_url': reverse('admin:imports_externaldatafile_changelist'),
            'opts': ExternalDataFile._meta,
        }
        return TemplateResponse(request, self.template_name, context)


class ProductReconciliationWorkflow(ReadOnlyReconciliationWorkflow):
    page_title = 'Product reconciliation'
    page_description = (
        'Read-only comparison between the approved Product staging rows and the '
        'operational Product table used by Calculator.'
    )

    def get_source(self, object_id):
        return get_object_or_404(
            ExternalDataFile,
            pk=object_id,
            file_type='PRODUCTS',
            status='VALIDATED',
        )

    def build_reconciliation(self, source):
        return build_product_reconciliation(source)

from __future__ import annotations

from abc import ABC, abstractmethod

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from apps.imports.forms import ProductSourceRejectedRowReviewForm
from apps.imports.models import ExternalDataFile, ProductSourceRejectedRow
from apps.imports.services.product_repair import (
    ProductRepairError,
    approve_product_source_repair,
    save_product_repair_proposal,
)
from apps.imports.services.xlsx_reader import value_to_text


class BulkReviewWorkflow(ABC):
    """Reusable Admin workflow for review, edit and selected-item approval."""

    template_name = 'admin/imports/bulk_review.html'
    workflow_key = ''
    page_title = ''
    page_description = ''
    selection_label = 'records'

    def __init__(self, admin_site):
        self.admin_site = admin_site

    @abstractmethod
    def has_permission(self, request) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_source(self, object_id):
        raise NotImplementedError

    @abstractmethod
    def get_items(self, source):
        raise NotImplementedError

    @abstractmethod
    def build_form(self, item, *, data=None):
        raise NotImplementedError

    @abstractmethod
    def build_row(self, item, form) -> dict:
        raise NotImplementedError

    @abstractmethod
    def process_item(self, request, item, form, *, approve: bool, note: str):
        raise NotImplementedError

    def view_name(self):
        return f'admin:imports_externaldatafile_{self.workflow_key}'

    def _selected_ids(self, request) -> list[int]:
        values = []
        for raw_value in request.POST.getlist('selected'):
            try:
                values.append(int(raw_value))
            except (TypeError, ValueError):
                continue
        return list(dict.fromkeys(values))

    def _bound_form(self, request, item, *, approve: bool, note: str):
        data = request.POST.copy()
        prefix = f'row-{item.pk}'
        data[f'{prefix}-review_note'] = note
        if approve:
            data['_approve_selected'] = '1'
        return self.build_form(item, data=data)

    def __call__(self, request, object_id):
        if not self.has_permission(request):
            raise PermissionDenied

        source = self.get_source(object_id)
        items = list(self.get_items(source))
        bound_forms = {}
        page_errors = []

        if request.method == 'POST':
            approve = '_approve_selected' in request.POST
            save = '_save_selected' in request.POST
            selected_ids = self._selected_ids(request)
            selectable = {item.pk: item for item in items if self.item_is_selectable(item)}
            selected_items = [selectable[item_id] for item_id in selected_ids if item_id in selectable]
            note = value_to_text(request.POST.get('bulk_review_note'))

            if not approve and not save:
                page_errors.append('Choose Save selected proposals or Approve selected into staging.')
            if not selected_items:
                page_errors.append('Select at least one pending row.')
            if approve and not note:
                page_errors.append('Enter a review note before approving selected rows.')
            if len(selected_items) != len(selected_ids):
                page_errors.append('One or more selected rows are no longer available for review.')

            for item in selected_items:
                form = self._bound_form(request, item, approve=approve, note=note)
                bound_forms[item.pk] = form
                if not form.is_valid():
                    page_errors.append(f'Row {self.item_label(item)} contains invalid values.')

            if not page_errors:
                try:
                    with transaction.atomic():
                        for item in selected_items:
                            self.process_item(
                                request,
                                item,
                                bound_forms[item.pk],
                                approve=approve,
                                note=note,
                            )
                except ProductRepairError as exc:
                    page_errors.append(str(exc))
                else:
                    action = 'approved into staging' if approve else 'saved as proposals'
                    messages.success(
                        request,
                        f'{len(selected_items)} {self.selection_label} {action}.',
                    )
                    return redirect(reverse(self.view_name(), args=[source.pk]))

        rows = []
        for item in items:
            form = bound_forms.get(item.pk) or self.build_form(item)
            rows.append(self.build_row(item, form))

        context = {
            **self.admin_site.each_context(request),
            'title': self.page_title,
            'page_description': self.page_description,
            'source': source,
            'rows': rows,
            'page_errors': list(dict.fromkeys(page_errors)),
            'pending_count': sum(1 for item in items if self.item_is_selectable(item)),
            'approved_count': sum(1 for item in items if not self.item_is_selectable(item)),
            'back_url': reverse('admin:imports_externaldatafile_changelist'),
            'opts': ExternalDataFile._meta,
        }
        return TemplateResponse(request, self.template_name, context)

    def item_is_selectable(self, item) -> bool:
        return True

    def item_label(self, item) -> str:
        return str(item.pk)


class ProductRejectedRowsBulkReview(BulkReviewWorkflow):
    workflow_key = 'review_product_rejections'
    page_title = 'Review rejected Product rows'
    page_description = (
        'Review the complete proposed text. Use Edit only when a correction is required.'
    )
    selection_label = 'Product row(s)'
    edit_field_names = (
        'code', 'name', 'description', 'category', 'length_mm', 'width_mm',
        'height_mm', 'cubic_m3', 'quantity', 'weight_kg', 'pallet', 'comment',
        'source_status',
    )

    def has_permission(self, request) -> bool:
        return request.user.is_active and request.user.is_staff and (
            request.user.is_superuser
            or (
                request.user.has_perm('imports.change_externaldatafile')
                and request.user.has_perm('imports.validate_external_data_file')
            )
        )

    def get_source(self, object_id):
        return get_object_or_404(
            ExternalDataFile,
            pk=object_id,
            file_type='PRODUCTS',
            status='VALIDATED',
        )

    def get_items(self, source):
        return (
            ProductSourceRejectedRow.objects.filter(external_file=source)
            .select_related('reviewed_by', 'staged_row')
            .order_by('source_row_number')
        )

    def build_form(self, item, *, data=None):
        return ProductSourceRejectedRowReviewForm(
            data=data,
            instance=item,
            prefix=f'row-{item.pk}',
        )

    @staticmethod
    def _value(form, field_name):
        value = form[field_name].value()
        return '' if value is None else value

    def build_row(self, item, form) -> dict:
        values = {name: self._value(form, name) for name in self.edit_field_names}
        dimensions = ' × '.join(
            value_to_text(values[name]) or '—'
            for name in ('length_mm', 'width_mm', 'height_mm')
        )
        edit_url = reverse(
            'admin:imports_productsourcerejectedrow_change',
            args=[item.pk],
        )
        return {
            'id': item.pk,
            'row_label': item.source_row_number,
            'record_key': values['code'] or (item.raw_values[0] if item.raw_values else ''),
            'issue': '; '.join(item.validation_errors or []),
            'status': item.get_repair_status_display(),
            'selectable': self.item_is_selectable(item),
            'display_cells': [
                {'label': 'Name', 'value': values['name'], 'css_class': 'bulk-review-name'},
                {
                    'label': 'Description',
                    'value': values['description'],
                    'css_class': 'bulk-review-description',
                },
                {'label': 'Comment', 'value': values['comment'], 'css_class': 'bulk-review-comment'},
            ],
            'detail_values': [
                ('Category', values['category'] or '—'),
                ('Dimensions mm', dimensions),
                ('Cubic m³', values['cubic_m3'] or '—'),
                ('Quantity', values['quantity'] or '—'),
                ('Weight kg', values['weight_kg'] or '—'),
                ('Pallet', values['pallet'] or '—'),
                ('Source status', values['source_status'] or '—'),
            ],
            'form': form,
            'edit_fields': [form[name] for name in self.edit_field_names],
            'edit_url': edit_url,
        }

    def process_item(self, request, item, form, *, approve: bool, note: str):
        function = approve_product_source_repair if approve else save_product_repair_proposal
        return function(
            item.pk,
            payload=form.repair_payload(),
            review_note=note,
            actor=request.user,
            request=request,
        )

    def item_is_selectable(self, item) -> bool:
        return item.repair_status != 'APPROVED'

    def item_label(self, item) -> str:
        return str(item.source_row_number)

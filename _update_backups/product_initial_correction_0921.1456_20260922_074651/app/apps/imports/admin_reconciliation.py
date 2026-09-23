from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from apps.imports.forms import (
    ProductReconciliationBulkForm,
    ProductReconciliationIndividualForm,
)
from apps.imports.models import (
    ExternalDataFile,
    ProductReconciliationDecision,
    ProductReconciliationRule,
)
from apps.imports.services.product_reconciliation import build_product_reconciliation
from apps.imports.services.product_reconciliation_workspace import (
    ProductReconciliationWorkspaceError,
    apply_rule_as_draft,
    build_workspace,
    field_decisions_from_preset,
    preview_decision,
    rows_for_group,
    save_product_reconciliation_decisions,
    save_reconciliation_rule,
)


GROUP_LABELS = {
    'ALL': 'All rows',
    'ALL_DIFFERENCES': 'All differences',
    'SOURCE_DIMENSIONS_ZERO': 'Source dimensions zero',
    'FREIGHT_TYPE_REVIEW': 'C/P requires manual review',
    'FREIGHT_TYPE_DIFFERENCES': 'C/P differs from pallet rule',
    'TEXT_ONLY': 'Text differences only',
    'PHYSICAL_DIFFERENCES': 'Other physical differences',
    'OTHER_DIFFERENCES': 'Other differences',
    'SOURCE_ONLY': 'Source only',
    'OPERATIONAL_ONLY': 'Operational only',
    'DUPLICATE_SOURCE': 'Duplicate source SKU',
    'SAME': 'Same',
}


class ReadOnlyReconciliationWorkflow(ABC):
    """Reusable, paginated comparison workflow with no operational Apply operation."""

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
    template_name = 'admin/imports/product_reconciliation_workspace.html'
    page_title = 'Product reconciliation workspace'
    page_description = (
        'Group, review and save draft Product decisions before any operational change.'
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

    def has_manage_permission(self, request):
        return request.user.is_superuser or request.user.has_perm(
            'imports.manage_product_reconciliation'
        )

    @staticmethod
    def _redirect(request, group_key, *, edit=''):
        query = {'group': group_key}
        if edit:
            query['edit'] = edit
        return redirect(f'{request.path}?{urlencode(query)}')

    @staticmethod
    def _search_rows(rows, search):
        if not search:
            return rows
        lowered = search.lower()
        return [
            row for row in rows
            if lowered in row['sku'].lower()
            or lowered in str(row['source_values'].get('name') or '').lower()
            or lowered in str(row['operational_values'].get('name') or '').lower()
        ]

    @staticmethod
    def _individual_initial(row):
        decision = row.get('decision')
        authorities = decision.field_decisions if decision else {}
        custom = decision.custom_values if decision else {}
        return {
            'sku': row['sku'],
            'name_authority': authorities.get('name', 'NO_CHANGE'),
            'custom_name': custom.get('name', ''),
            'description_authority': authorities.get('description', 'NO_CHANGE'),
            'custom_description': custom.get('description', ''),
            'dimensions_authority': authorities.get('dimensions', 'NO_CHANGE'),
            'custom_length_m': custom.get('length_m'),
            'custom_width_m': custom.get('width_m'),
            'custom_height_m': custom.get('height_m'),
            'weight_authority': authorities.get('weight', 'NO_CHANGE'),
            'custom_weight_kg': custom.get('weight_kg'),
            'cubic_authority': authorities.get('cubic', 'NO_CHANGE'),
            'custom_cubic_m3': custom.get('cubic_m3'),
            'freight_type_authority': authorities.get(
                'freight_type',
                'SOURCE' if row['source_values'].get('freight_type') in {'C', 'P'} else 'CUSTOM',
            ),
            'custom_freight_type': custom.get('freight_type', ''),
            'notes': decision.notes if decision else '',
        }

    def _handle_post(self, request, source, rows, group_key, group_rows):
        if not self.has_manage_permission(request):
            raise PermissionDenied
        action = str(request.POST.get('workspace_action') or '')
        try:
            if action == 'save_bulk':
                form = ProductReconciliationBulkForm(
                    request.POST,
                    available_skus=[row['sku'] for row in group_rows],
                )
                if not form.is_valid():
                    errors = '; '.join(
                        message
                        for messages_list in form.errors.values()
                        for message in messages_list
                    )
                    raise ProductReconciliationWorkspaceError(
                        errors or 'Correct the bulk decision form before saving.'
                    )
                scope = str(request.POST.get('scope') or 'selected')
                skus = (
                    [row['sku'] for row in group_rows]
                    if scope == 'group'
                    else form.cleaned_data['selected_skus']
                )
                if scope == 'group' and len(skus) > 2000:
                    raise ProductReconciliationWorkspaceError(
                        'This group is too large for one draft operation. '
                        'Source-only rows already remain reference-only by default; '
                        'otherwise select the required rows from the current page.'
                    )
                decisions = field_decisions_from_preset(form.cleaned_data['preset'])
                saved = save_product_reconciliation_decisions(
                    source,
                    skus=skus,
                    field_decisions=decisions,
                    notes=form.cleaned_data['notes'],
                    actor=request.user,
                    request=request,
                )
                if form.cleaned_data['save_as_rule']:
                    save_reconciliation_rule(
                        source,
                        name=form.cleaned_data['rule_name'],
                        group_key=group_key,
                        field_decisions=decisions,
                        actor=request.user,
                        request=request,
                    )
                messages.success(
                    request,
                    f'{len(saved)} draft decision(s) saved. Operational Products were not changed.',
                )
                return self._redirect(request, group_key)

            if action == 'save_individual':
                form = ProductReconciliationIndividualForm(request.POST)
                if not form.is_valid():
                    errors = '; '.join(
                        message
                        for messages_list in form.errors.values()
                        for message in messages_list
                    )
                    raise ProductReconciliationWorkspaceError(
                        errors or 'Correct the individual decision form before saving.'
                    )
                saved = save_product_reconciliation_decisions(
                    source,
                    skus=[form.cleaned_data['sku']],
                    field_decisions=form.field_decisions(),
                    custom_values=form.custom_values(),
                    notes=form.cleaned_data['notes'],
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    f'Draft decision saved for {saved[0].product_code_normalized}. '
                    'Operational Products were not changed.',
                )
                return self._redirect(request, group_key, edit=saved[0].product_code_normalized)

            if action == 'apply_rule':
                rule = get_object_or_404(
                    ProductReconciliationRule,
                    pk=request.POST.get('rule_id'),
                    client=source.client,
                    active=True,
                )
                saved = apply_rule_as_draft(
                    source,
                    rule=rule,
                    rows=rows,
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    f'Rule {rule.name} created {len(saved)} draft decision(s). '
                    'Operational Products were not changed.',
                )
                return self._redirect(request, rule.group_key)
        except ProductReconciliationWorkspaceError as exc:
            messages.error(request, str(exc))
            return self._redirect(request, group_key, edit=request.POST.get('sku', ''))
        raise PermissionDenied('Unsupported reconciliation workspace action.')

    def __call__(self, request, object_id):
        if not self.has_permission(request):
            raise PermissionDenied
        source = self.get_source(object_id)
        rows, summary = build_workspace(source)
        blocked = summary['pending_rejected'] > 0
        legacy_status = str(request.GET.get('status') or '').upper()
        legacy_group = {
            'ALL': 'ALL',
            'NEEDS_REVIEW': 'ALL_DIFFERENCES',
            'DIFFERENT': 'ALL_DIFFERENCES',
            'SOURCE_ONLY': 'SOURCE_ONLY',
            'OPERATIONAL_ONLY': 'OPERATIONAL_ONLY',
            'DUPLICATE_SOURCE': 'DUPLICATE_SOURCE',
            'SAME': 'SAME',
        }.get(legacy_status, '')
        group_key = str(
            request.POST.get('group')
            or request.GET.get('group')
            or legacy_group
            or 'ALL_DIFFERENCES'
        ).upper()
        if group_key not in GROUP_LABELS:
            group_key = 'ALL_DIFFERENCES'
        group_rows = rows_for_group(rows, group_key)

        if request.method == 'POST':
            if blocked:
                messages.error(
                    request,
                    'Complete rejected-row review before saving reconciliation decisions.',
                )
                return self._redirect(request, group_key)
            response = self._handle_post(request, source, rows, group_key, group_rows)
            if response is not None:
                return response

        search = str(request.GET.get('q') or '').strip()
        filtered = self._search_rows(group_rows, search)
        filtered.sort(key=lambda row: (row['sku'], row['source_row_number'] or 0))
        page = Paginator(filtered, self.page_size).get_page(request.GET.get('page'))
        bulk_form = ProductReconciliationBulkForm(
            available_skus=[row['sku'] for row in page.object_list]
        )

        edit_sku = str(request.GET.get('edit') or '').strip()
        edit_row = next((row for row in rows if row['sku'] == edit_sku), None)
        individual_form = None
        if edit_row:
            individual_form = ProductReconciliationIndividualForm(
                initial=self._individual_initial(edit_row)
            )

        preview_rows = []
        preview_mode = str(request.GET.get('mode') or '').lower() == 'preview'
        if preview_mode:
            row_map = {row['sku']: row for row in rows}
            for decision in ProductReconciliationDecision.objects.filter(
                external_file=source
            ).order_by('product_code_normalized'):
                row = row_map.get(decision.product_code_normalized)
                if row:
                    preview_rows.append(preview_decision(row, decision))

        rules = ProductReconciliationRule.objects.filter(
            client=source.client,
            active=True,
        ).order_by('group_key', 'name')
        navigation_keys = (
            'ALL_DIFFERENCES',
            'SOURCE_DIMENSIONS_ZERO',
            'FREIGHT_TYPE_REVIEW',
            'FREIGHT_TYPE_DIFFERENCES',
            'TEXT_ONLY',
            'PHYSICAL_DIFFERENCES',
            'SOURCE_ONLY',
            'OPERATIONAL_ONLY',
            'DUPLICATE_SOURCE',
        )
        group_navigation = [
            {
                'key': key,
                'label': GROUP_LABELS[key],
                'count': summary['group_counts'].get(key, 0),
            }
            for key in navigation_keys
        ]
        context = {
            **self.admin_site.each_context(request),
            'title': self.page_title,
            'page_description': self.page_description,
            'source': source,
            'summary': summary,
            'page_obj': page,
            'search': search,
            'result_count': len(filtered),
            'group_result_count': len(group_rows),
            'blocked': blocked,
            'back_url': reverse('admin:imports_externaldatafile_changelist'),
            'opts': ExternalDataFile._meta,
            'group_labels': GROUP_LABELS,
            'group_navigation': group_navigation,
            'selected_group': group_key,
            'selected_group_label': GROUP_LABELS[group_key],
            'bulk_form': bulk_form,
            'edit_row': edit_row,
            'individual_form': individual_form,
            'can_manage': self.has_manage_permission(request),
            'rules': rules,
            'preview_mode': preview_mode,
            'preview_rows': preview_rows,
        }
        return TemplateResponse(request, self.template_name, context)

from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlencode

from django.contrib import messages
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from apps.authentication_gateway.services import allowed_clients_for, CalculatorAccessDenied, is_django_administrator
from django.template.response import TemplateResponse
from django.urls import reverse

from apps.imports.forms import (
    ProductReconciliationBulkForm,
    ProductReconciliationIndividualForm,
)
from apps.imports.models import (
    ExternalDataFile,
    ProductMaster,
    ProductCorrectionRound,
    ProductReconciliationDecision,
    ProductReconciliationRule,
)
from apps.imports.services.product_reconciliation import build_product_reconciliation
from apps.imports.services.product_master import reconciliation_rows_for_customer
from apps.imports.services.xlsx_reader import SourceImportError
from apps.clients.models import Client, Customer
from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from apps.imports.services.product_reconciliation_workspace import (
    ProductReconciliationWorkspaceError,
    apply_rule_as_draft,
    build_workspace,
    field_decisions_from_preset,
    has_active_product_apply,
    preview_decision,
    rows_for_group,
    save_product_reconciliation_decisions,
    save_reconciliation_rule,
    RECONCILABLE_FIELDS,
)
from apps.imports.services.product_reconciliation_apply import (
    ProductReconciliationApplyBlocked,
    apply_product_reconciliation,
    build_product_apply_plan,
    create_recommended_product_drafts,
    latest_product_apply_batch,
    rollback_latest_product_apply,
)
from apps.imports.services.product_reconciliation_memory import (
    ProductReconciliationMemoryError,
    adopt_operational_product_memories,
    backfill_applied_product_memories,
    prepare_exact_memory_drafts,
    reuse_all_exact_product_memories,
    reuse_product_memories,
)
from apps.imports.services.product_correction_rounds import (
    CorrectionRoundError, start_correction_round, save_correction_decision,
    correction_preview, apply_correction_round, rollback_correction_round,
    bulk_dimension_candidates, is_zero_source_dimensions_candidate,
    save_bulk_operational_dimensions,
    bulk_field_candidates, save_bulk_field_decisions,
    save_inline_correction_decisions, corrected_skus_for_source,
    autosave_correction_field,
)


GROUP_LABELS = {
    'ALL': 'All rows',
    'ALL_DIFFERENCES': 'All differences',
    'SOURCE_DIMENSIONS_ZERO': 'Source dimensions zero',
    'DIMENSION_UNIT_REVIEW': 'Possible dimension unit mismatch',
    'MEMORY_EXACT': 'Previously resolved — identical Source',
    'MEMORY_SOURCE_CHANGED': 'Previous solution — Source changed',
    'MEMORY_NEW_ISSUE': 'New issue — no previous solution',
    'MEMORY_RULE_MATCH': 'Approved reusable rule available',
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


CORRECTION_GROUPS = {
    'ALL': 'All differences', 'SOURCE_DIMENSIONS_ZERO': 'Source dimensions zero',
    'DIMENSIONS': 'Dimensions', 'WEIGHT': 'Weight', 'CUBIC': 'Cubic',
    'MULTIPLE': 'Multiple fields',
}
CORRECTION_STATUSES = {
    'OPEN': 'Open (unreviewed and draft)', 'UNREVIEWED': 'Unreviewed',
    'DRAFT': 'Draft', 'CORRECTED': 'Already corrected', 'ALL': 'All',
}


def filter_correction_rows(rows, *, group='ALL', status='OPEN', query='',
                           draft_skus=(), corrected_skus=()):
    """The same row filter serves display and server-side select-all."""
    group = group if group in CORRECTION_GROUPS else 'ALL'
    status = status if status in CORRECTION_STATUSES else 'OPEN'
    draft_skus, corrected_skus = set(draft_skus), set(corrected_skus)
    query = str(query or '').strip().lower()
    result = []
    for row in rows:
        if row['status'] != 'DIFFERENT' or not row.get('source') or not row.get('product'):
            continue
        changed = set(row['changed_fields'])
        if group == 'SOURCE_DIMENSIONS_ZERO' and not is_zero_source_dimensions_candidate(row):
            continue
        if group in {'DIMENSIONS', 'WEIGHT', 'CUBIC'} and group.lower() not in changed:
            continue
        if group == 'MULTIPLE' and len(changed) < 2:
            continue
        sku = row['sku']
        if status == 'OPEN' and sku in corrected_skus:
            continue
        if status == 'UNREVIEWED' and (sku in corrected_skus or sku in draft_skus):
            continue
        if status == 'DRAFT' and sku not in draft_skus:
            continue
        if status == 'CORRECTED' and sku not in corrected_skus:
            continue
        if query and query not in sku.lower() and query not in str(row['source_values'].get('name') or '').lower() and query not in str(row['operational_values'].get('name') or '').lower():
            continue
        result.append(row)
    return result


def correction_table_fields(row, form):
    """Present the existing six per-field authorities beside both compared values."""
    spec = {
        'name': ('Name', ('name',)),
        'description': ('Description', ('description',)),
        'dimensions': ('Dimensions (m)', ('length_m', 'width_m', 'height_m')),
        'weight': ('Weight (kg)', ('weight_kg',)),
        'cubic': ('Cubic (m³)', ('cubic_m3',)),
        'freight_type': ('Case/Pallet', ('freight_type',)),
    }
    visible, hidden = [], []
    for field in RECONCILABLE_FIELDS:
        label, value_keys = spec[field]
        authority = form[f'{field}_authority']
        customs = [form[f'custom_{key}'] for key in value_keys]
        if field in row['changed_fields']:
            visible.append({
                'key': field, 'label': label,
                'source': ' × '.join(str(row['source_values'].get(key, '')) for key in value_keys),
                'current': ' × '.join(str(row['operational_values'].get(key, '')) for key in value_keys),
                'authority': authority, 'customs': customs,
            })
        else:
            hidden.extend([authority, *customs])
    return visible, hidden


def reconciliation_progress(source, rows):
    """Summarise existing decisions without confusing physical differences with open work."""
    initial = {decision.product_code_normalized: decision for decision in
               ProductReconciliationDecision.objects.filter(external_file=source)}
    rounds = list(ProductCorrectionRound.objects.filter(
        external_file=source, status__in=['DRAFT', 'APPLIED'],
    ).prefetch_related('decisions').order_by('pk'))
    current = next((item for item in reversed(rounds) if item.status == 'DRAFT'), None)
    history = {}
    for item in rounds:
        for decision in item.decisions.all():
            history.setdefault(decision.sku, []).append((item, decision))
    counts = {'needs_review': 0, 'draft': 0, 'applied': 0, 'partial': 0,
              'physical': 0, 'draft_decisions': 0}
    counts['draft_decisions'] = (
        current.decisions.count() if current else 0
    ) + sum(d.decision_status in {'DRAFT', 'READY'} for d in initial.values())
    for row in rows:
        sku = row['sku']
        differing = set(row.get('changed_fields') or ())
        if row['status'] == 'DIFFERENT' and differing & {'dimensions', 'weight', 'cubic'}:
            counts['physical'] += 1
        original = initial.get(sku)
        related = history.get(sku, [])
        applied_fields = set()
        draft_fields = set()
        if original:
            target = applied_fields if original.decision_status == 'APPLIED' else draft_fields
            target.update(field for field, choice in original.field_decisions.items()
                          if choice in {'SOURCE', 'OPERATIONAL', 'CUSTOM'})
        for item, decision in related:
            target = applied_fields if item.status == 'APPLIED' else draft_fields
            target.update(field for field, choice in decision.field_decisions.items()
                          if choice in {'SOURCE', 'OPERATIONAL', 'CUSTOM'})
        reviewed = applied_fields | draft_fields
        if row['status'] in {'DIFFERENT', 'OPERATIONAL_ONLY', 'DUPLICATE_SOURCE'}:
            if differing and reviewed & differing and differing - reviewed:
                state = 'partial'
            elif (differing and differing - reviewed) or (not differing and not original and not related):
                state = 'needs_review'
            elif (original and original.decision_status != 'APPLIED') or any(
                item.status == 'DRAFT' for item, _ in related
            ):
                state = 'draft'
            else:
                state = 'applied'
            counts[state] += 1
        elif original and original.decision_status == 'APPLIED' or any(
            item.status == 'APPLIED' for item, _ in related
        ):
            state = 'applied'
            counts['applied'] += 1
        else:
            state = 'reference'
        row['review_state'] = state
        row['latest_correction_round'] = related[-1][0] if related else None
        row['pending_fields'] = sorted(differing - reviewed)
    counts['products_needing_review'] = counts['needs_review'] + counts['partial']
    counts['open_round'] = current
    return counts


def preview_changed_values(items):
    """Show only actual changes in both existing Preview flows."""
    labels = {'length_m': 'Length (m)', 'width_m': 'Width (m)', 'height_m': 'Height (m)',
              'weight_kg': 'Weight (kg)', 'cubic_m3': 'Cubic (m³)',
              'freight_type': 'Case/Pallet', 'name': 'Name', 'description': 'Description'}
    for item in items:
        current = item['row'].get('operational_values') or {}
        proposed = item.get('proposed_values') or {}
        item['changed_values'] = [
            {'label': labels.get(key, key), 'current': current.get(key), 'proposed': value}
            for key, value in proposed.items()
            if str(current.get(key) if current.get(key) is not None else '')
               != str(value if value is not None else '')
        ]
    return items


class ReadOnlyReconciliationWorkflow(ABC):
    """Reusable, paginated comparison workflow with no operational Apply operation."""

    template_name = 'admin/imports/reconciliation.html'
    page_title = ''
    page_description = ''
    page_size = 100

    def __init__(self, admin_site):
        self.admin_site = admin_site

    @abstractmethod
    def get_source(self, request, object_id):
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
        source = self.get_source(request, object_id)
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


class ProductMasterReadOnlyReconciliation(ReadOnlyReconciliationWorkflow):
    """Use the existing comparison view for one authorised Client, without staging."""

    page_title = 'Product Master reconciliation comparison'
    page_description = 'Read-only comparison; decisions, memory and Products remain unchanged.'

    def __call__(self, request, object_id, client_id):
        if not self.has_permission(request):
            raise PermissionDenied
        if request.method != 'GET':
            return HttpResponseNotAllowed(['GET'])
        self.client_id = client_id
        response = super().__call__(request, object_id)
        response.context_data['back_url'] = reverse(
            'admin:imports_productmaster_change', args=[object_id],
        ) if is_django_administrator(request.user) else reverse('admin:index')
        response.context_data['back_label'] = 'Product Masters'
        return response

    def get_source(self, request, object_id):
        if request.user.is_superuser:
            clients = Client.objects.all()
        else:
            try:
                clients = allowed_clients_for(request.user)
            except CalculatorAccessDenied as exc:
                raise PermissionDenied from exc
        client = get_object_or_404(clients, pk=self.client_id)
        customer = get_object_or_404(Customer, linked_client=client, is_special=False)
        master = get_object_or_404(ProductMaster, pk=object_id, status='VALIDATED')
        try:
            rows = reconciliation_rows_for_customer(master, customer)
        except SourceImportError as exc:
            # Do not disclose data or validation details from other Customers.
            raise Http404('This Product Master cannot be compared for this Customer.') from exc
        source = ExternalDataFile(
            client=client, file_type='PRODUCTS', status='VALIDATED',
            original_filename=master.original_filename,
        )
        source.master_rows = rows
        return source

    def build_reconciliation(self, source):
        return build_workspace(
            source, source_rows=source.master_rows, pending_rejected=0,
            include_decisions=False,
        )


class ProductReconciliationWorkflow(ReadOnlyReconciliationWorkflow):
    template_name = 'admin/imports/product_reconciliation_workspace.html'
    page_title = 'Product reconciliation workspace'
    page_description = (
        'Group, review and save draft Product decisions before any operational change.'
    )

    def get_source(self, request, object_id):
        if request.user.is_superuser:
            sources = ExternalDataFile.objects.all()
        else:
            try:
                sources = ExternalDataFile.objects.filter(client__in=allowed_clients_for(request.user))
            except CalculatorAccessDenied:
                raise PermissionDenied
        return get_object_or_404(
            sources,
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

    def _correction_view(self, request, source):
        if not self.has_manage_permission(request):
            raise PermissionDenied
        posted_actions = request.POST.getlist('correction_action')
        action = posted_actions[-1] if posted_actions else ''
        selected_id = request.POST.get('round_id') or request.GET.get('round')
        round_obj = get_object_or_404(
            ProductCorrectionRound, pk=selected_id, external_file=source
        ) if selected_id else None
        base_url = f'{request.path}?mode=correction'
        bulk_preview = None
        try:
            if request.method == 'POST':
                if action == 'autosave_field':
                    if not round_obj:
                        return JsonResponse({'error': 'Select an open correction round.'}, status=400)
                    try:
                        decision = autosave_correction_field(
                            round_obj.pk, sku=str(request.POST.get('sku') or '').strip(),
                            field=request.POST.get('field'), authority=request.POST.get('authority'),
                            notes=request.POST.get('notes'),
                            confirm_source_dimensions=request.POST.get('confirm_source_dimensions') == 'yes',
                            allow_reopen=request.POST.get('allow_reopen') == 'yes',
                            actor=request.user, request=request,
                        )
                    except CorrectionRoundError as exc:
                        return JsonResponse({'error': str(exc)}, status=400)
                    updated_rows, _ = build_workspace(source)
                    updated_progress = reconciliation_progress(source, updated_rows)
                    return JsonResponse({'status': 'saved', 'sku': decision.sku,
                                         'draft_count': updated_progress['draft_decisions'],
                                         'pending_count': updated_progress['products_needing_review']})
                if action == 'start':
                    round_obj = start_correction_round(source.pk, actor=request.user, request=request)
                    return redirect(f'{base_url}&round={round_obj.pk}')
                if not round_obj:
                    raise CorrectionRoundError('Select a correction round.')
                if action == 'preview_bulk_dimensions':
                    if request.POST.get('select_all_eligible') == 'yes':
                        all_rows, _ = build_workspace(source)
                        prior_skus = set(
                            ProductCorrectionRound.objects.filter(
                                external_file=source, status='APPLIED',
                            ).values_list('decisions__sku', flat=True)
                        ) if request.POST.get('show_all') != 'yes' else set()
                        search = str(request.POST.get('q') or '').strip().lower()
                        skus = [
                            row['sku'] for row in all_rows
                            if is_zero_source_dimensions_candidate(row)
                            and row['sku'] not in prior_skus
                            and (not search or search in row['sku'].lower()
                                 or search in str(row['source_values'].get('name') or '').lower())
                        ]
                    else:
                        skus = request.POST.getlist('selected_skus')
                    bulk_preview = bulk_dimension_candidates(round_obj, skus)
                    bulk_preview['token'] = signing.dumps({
                        'round': round_obj.pk, 'source': source.pk,
                        'selected': list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip())),
                        'eligible': bulk_preview['eligible'],
                    }, salt='product-correction-zero-dimensions', compress=True)
                    bulk_preview['notes'] = str(request.POST.get('notes') or '').strip()
                if action == 'save_bulk_dimensions':
                    try:
                        selection = signing.loads(
                            request.POST.get('preview_token', ''),
                            salt='product-correction-zero-dimensions', max_age=1800,
                        )
                    except signing.BadSignature as exc:
                        raise CorrectionRoundError('Preview expired or changed. Review the SKUs again.') from exc
                    if selection.get('round') != round_obj.pk or selection.get('source') != source.pk:
                        raise CorrectionRoundError('Preview belongs to a different correction round.')
                    result = save_bulk_operational_dimensions(
                        round_obj.pk, skus=selection['selected'],
                        expected_eligible=selection['eligible'],
                        notes=request.POST.get('notes'), actor=request.user, request=request,
                    )
                    messages.success(request, f"{len(result['eligible'])} dimension decision(s) saved in the draft; Products unchanged. {len(result['excluded'])} excluded.")
                    return redirect(f'{base_url}&round={round_obj.pk}&preview=1')
                if action == 'preview_bulk_field':
                    selected = request.POST.getlist('selected_skus')
                    if request.POST.get('select_all_filtered') == 'yes':
                        all_rows, _ = build_workspace(source)
                        draft_skus = set(round_obj.decisions.values_list('sku', flat=True))
                        corrected_skus = corrected_skus_for_source(source)
                        filtered = filter_correction_rows(
                            all_rows, group=request.POST.get('group'),
                            status=request.POST.get('status'), query=request.POST.get('q'),
                            draft_skus=draft_skus, corrected_skus=corrected_skus,
                        )
                        selected = [row['sku'] for row in filtered]
                    field = request.POST.get('bulk_field', '')
                    authority = request.POST.get('bulk_authority', '')
                    bulk_field_preview = bulk_field_candidates(
                        round_obj, selected, field=field, authority=authority,
                    )
                    bulk_field_preview.update({
                        'field': field, 'authority': authority,
                        'notes': str(request.POST.get('bulk_reason') or '').strip(),
                    })
                    bulk_field_preview['token'] = signing.dumps({
                        'round': round_obj.pk, 'source': source.pk,
                        'selected': list(dict.fromkeys(selected)),
                        'eligible': bulk_field_preview['eligible'],
                        'field': field, 'authority': authority,
                    }, salt='product-correction-bulk-field', compress=True)
                if action == 'save_bulk_field':
                    try:
                        selection = signing.loads(
                            request.POST.get('preview_token', ''),
                            salt='product-correction-bulk-field', max_age=1800,
                        )
                    except signing.BadSignature as exc:
                        raise CorrectionRoundError('Bulk Preview expired or changed. Review the SKUs again.') from exc
                    if selection.get('round') != round_obj.pk or selection.get('source') != source.pk:
                        raise CorrectionRoundError('Bulk Preview belongs to another correction round.')
                    result = save_bulk_field_decisions(
                        round_obj.pk, skus=selection['selected'],
                        expected_eligible=selection['eligible'],
                        field=selection['field'], authority=selection['authority'],
                        notes=request.POST.get('bulk_reason'), actor=request.user,
                        request=request,
                    )
                    messages.success(request, f"{len(result['eligible'])} field decision(s) saved in draft; Products unchanged. {len(result['excluded'])} excluded.")
                    return redirect(f'{base_url}&round={round_obj.pk}&preview=1')
                if action in {'save_inline', 'save_selected_inline'}:
                    skus = (
                        request.POST.getlist('selected_skus') if action == 'save_selected_inline'
                        else [str(request.POST.get('inline_sku') or '').strip()]
                    )
                    if not skus or not all(skus) or len(skus) != len(set(skus)):
                        raise CorrectionRoundError('Select distinct Product rows to save.')
                    row_map = {row['sku']: row for row in build_workspace(source)[0]}
                    entries = []
                    for sku in skus:
                        row = row_map.get(sku)
                        if not row or not row.get('product') or row['status'] != 'DIFFERENT':
                            raise CorrectionRoundError(f'{sku}: no matched Product with a remaining difference.')
                        form = ProductReconciliationIndividualForm(
                            request.POST, prefix=f"r{row['product'].pk}",
                        )
                        if not form.is_valid():
                            raise CorrectionRoundError(f"{sku}: " + '; '.join(
                                str(error) for errors in form.errors.values() for error in errors
                            ))
                        if form.cleaned_data['sku'] != sku:
                            raise CorrectionRoundError(f'{sku}: selected SKU and form do not match.')
                        entries.append({
                            'sku': sku, 'field_decisions': form.field_decisions(),
                            'custom_values': form.custom_values(),
                            'notes': form.cleaned_data['notes'] or request.POST.get('bulk_reason'),
                            'confirm_source_dimensions': sku in request.POST.getlist('confirmed_source_skus'),
                            'allow_reopen': sku in request.POST.getlist('confirmed_reopen_skus'),
                        })
                    count = save_inline_correction_decisions(
                        round_obj.pk, entries=entries, actor=request.user, request=request,
                    )
                    messages.success(request, f'{count} correction decision(s) saved in draft. Products unchanged.')
                    return redirect(f'{base_url}&round={round_obj.pk}&preview=1')
                if action == 'save':
                    form = ProductReconciliationIndividualForm(request.POST)
                    if not form.is_valid():
                        raise CorrectionRoundError('; '.join(
                            str(error) for errors in form.errors.values() for error in errors
                        ))
                    saved = save_correction_decision(
                        round_obj.pk, sku=form.cleaned_data['sku'],
                        field_decisions=form.field_decisions(), custom_values=form.custom_values(),
                        notes=form.cleaned_data['notes'], actor=request.user, request=request,
                        confirm_source_dimensions=request.POST.get('confirm_source_dimensions') == 'yes',
                    )
                    messages.success(request, f'{saved.sku}: correction draft saved. Product unchanged.')
                    return redirect(f'{base_url}&round={round_obj.pk}&preview=1')
                if action == 'apply':
                    if request.POST.get('confirm_apply') != 'yes':
                        raise CorrectionRoundError('Confirm that you reviewed the correction Preview.')
                    apply_correction_round(round_obj.pk, actor=request.user, request=request)
                    messages.success(request, 'Correction round applied. Prior decisions remain in history.')
                    return redirect(f'{request.path}?group=ALL_DIFFERENCES')
                if action == 'rollback':
                    if request.POST.get('confirm_rollback') != 'yes':
                        raise CorrectionRoundError('Confirm correction round rollback.')
                    rollback_correction_round(round_obj.pk, actor=request.user, request=request)
                    messages.success(request, 'Correction round rolled back.')
                    return redirect(f'{base_url}&round={round_obj.pk}')
                if action == 'discard':
                    if round_obj.status != 'DRAFT':
                        raise CorrectionRoundError('Only a draft round can be discarded.')
                    round_obj.status = 'DISCARDED'
                    round_obj.save(update_fields=['status'])
                    messages.success(request, 'Draft round discarded. Operational Products unchanged.')
                    return redirect(base_url)
                if action not in {'preview_bulk_dimensions', 'preview_bulk_field'}:
                    raise PermissionDenied('Unsupported correction action.')
        except CorrectionRoundError as exc:
            messages.error(request, str(exc))
            return redirect(f'{base_url}&round={round_obj.pk}' if round_obj else base_url)

        history = ProductCorrectionRound.objects.filter(external_file=source).order_by('-pk')
        if not round_obj:
            round_obj = history.filter(status='DRAFT').first() or history.first()
        rows, summary = build_workspace(source)
        reviewed_skus = corrected_skus_for_source(source)
        draft_by_sku = {
            decision.sku: decision for decision in (
                round_obj.decisions.all() if round_obj and round_obj.status == 'DRAFT' else []
            )
        }
        physical_count = sum(
            row['status'] == 'DIFFERENT' and
            bool(set(row['changed_fields']).intersection({'dimensions', 'weight', 'cubic'}))
            for row in rows
        )
        query = str(request.GET.get('q') or request.POST.get('q') or '').strip().lower()
        selected_group = str(request.GET.get('group') or request.POST.get('group') or 'ALL')
        if selected_group not in CORRECTION_GROUPS:
            selected_group = 'ALL'
        selected_status = str(request.GET.get('status') or request.POST.get('status') or (
            'ALL' if request.GET.get('show') == 'all' else 'OPEN'
        ))
        if selected_status not in CORRECTION_STATUSES:
            selected_status = 'OPEN'
        relevant = filter_correction_rows(
            rows, group=selected_group, status=selected_status, query=query,
            draft_skus=draft_by_sku, corrected_skus=reviewed_skus,
        )
        zero_dimensions_count = sum(
            is_zero_source_dimensions_candidate(row) for row in rows
        )
        page = Paginator(relevant, self.page_size).get_page(request.GET.get('page'))
        table_rows = []
        if round_obj and round_obj.status == 'DRAFT' and request.GET.get('preview') != '1':
            for row in page:
                sku, previous = row['sku'], draft_by_sku.get(row['sku'])
                initial = {'sku': sku, 'notes': previous.notes if previous else ''}
                for field in RECONCILABLE_FIELDS:
                    initial[f'{field}_authority'] = (
                        previous.field_decisions.get(field, 'NO_CHANGE') if previous else 'NO_CHANGE'
                    )
                if previous:
                    initial.update({f'custom_{key}': value for key, value in previous.custom_values.items()})
                form = ProductReconciliationIndividualForm(
                    initial=initial, prefix=f"r{row['product'].pk}",
                )
                fields, hidden_fields = correction_table_fields(row, form)
                table_rows.append({
                    'row': row, 'form': form, 'fields': fields, 'hidden_fields': hidden_fields,
                    'decision': previous, 'corrected': sku in reviewed_skus,
                    'multiple': len(fields) > 1,
                })
        selected_sku = str(request.GET.get('edit') or '').strip()
        edit_row = next((row for row in relevant if row['sku'] == selected_sku), None)
        form = None
        decision_history = []
        if edit_row and round_obj and round_obj.status == 'DRAFT':
            existing = round_obj.decisions.filter(sku=selected_sku).first()
            fields = ('name', 'description', 'dimensions', 'weight', 'cubic', 'freight_type')
            initial = {'sku': selected_sku, 'notes': existing.notes if existing else ''}
            for field in fields:
                initial[f'{field}_authority'] = (
                    existing.field_decisions.get(field, 'NO_CHANGE') if existing else 'NO_CHANGE'
                )
            if existing:
                for key, value in existing.custom_values.items():
                    initial[f'custom_{key}'] = value
            form = ProductReconciliationIndividualForm(initial=initial)
            initial_decision = ProductReconciliationDecision.objects.filter(
                external_file=source, product_code_normalized=selected_sku,
                decision_status='APPLIED',
            ).first()
            if initial_decision:
                decision_history.append({
                    'label': 'Initial Apply', 'decisions': initial_decision.field_decisions,
                    'reason': initial_decision.notes, 'date': initial_decision.applied_at,
                })
            for prior in ProductCorrectionRound.objects.filter(
                external_file=source, status='APPLIED'
            ).order_by('pk'):
                prior_decision = prior.decisions.filter(sku=selected_sku).first()
                if prior_decision:
                    decision_history.append({
                        'label': f'Correction round {prior.pk}',
                        'decisions': prior_decision.field_decisions,
                        'reason': prior_decision.notes, 'date': prior.applied_at,
                    })
        plan = correction_preview(round_obj) if round_obj else None
        if plan:
            preview_changed_values(plan['items'])
        progress = reconciliation_progress(source, rows)
        return TemplateResponse(request, 'admin/imports/product_correction_round.html', {
            **self.admin_site.each_context(request), 'title': 'Product correction rounds',
            'source': source, 'opts': ExternalDataFile._meta,
            'back_url': request.path, 'round': round_obj, 'history': history,
            'page_obj': page, 'edit_row': edit_row, 'individual_form': form,
            'plan': plan, 'preview_mode': request.GET.get('preview') == '1',
            'summary': summary, 'query': query,
            'physical_count': physical_count, 'reviewed_count': len(reviewed_skus),
            'decision_history': decision_history,
            'selected_group': selected_group,
            'zero_dimensions_count': zero_dimensions_count,
            'bulk_preview': bulk_preview,
            'bulk_field_preview': bulk_field_preview if request.method == 'POST' and action == 'preview_bulk_field' else None,
            'table_rows': table_rows, 'selected_status': selected_status,
            'correction_groups': CORRECTION_GROUPS.items(),
            'correction_statuses': CORRECTION_STATUSES.items(),
            'result_count': len(relevant),
            'progress': progress,
        })

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
        action_values = request.POST.getlist('workspace_action')
        action = str(action_values[-1] if action_values else '')
        if has_active_product_apply(source) and action != 'rollback_apply':
            messages.error(
                request,
                'This Product source has an active Apply. Roll it back before preparing or applying decisions.',
            )
            return self._redirect(request, group_key)
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
                row_action = (
                    'DELETE'
                    if form.cleaned_data['preset'] == 'REMOVE_OPERATIONAL'
                    else 'UPDATE'
                )
                if row_action == 'DELETE' and form.cleaned_data['save_as_rule']:
                    raise ProductReconciliationWorkspaceError(
                        'Protected removals cannot be saved as an automatic reusable rule.'
                    )
                saved = save_product_reconciliation_decisions(
                    source,
                    skus=skus,
                    field_decisions=decisions,
                    notes=form.cleaned_data['notes'],
                    actor=request.user,
                    request=request,
                    row_action=row_action,
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

            if action == 'create_recommended':
                saved = create_recommended_product_drafts(
                    source,
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    f'{len(saved)} recommended draft decision(s) prepared. '
                    'Review the preview before Apply.',
                )
                return redirect(f'{request.path}?group=ALL_DIFFERENCES&mode=preview')

            if action == 'reuse_memory':
                prepared = reuse_product_memories(
                    source,
                    skus=request.POST.getlist('selected_skus'),
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    f'{len(prepared)} previous approved solution(s) prepared as drafts. '
                    'Review the Preview before Apply.',
                )
                return redirect(f'{request.path}?group={group_key}&mode=preview')

            if action == 'reuse_all_exact_memory':
                prepared = reuse_all_exact_product_memories(
                    source,
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    f'{len(prepared)} identical previous solution(s) prepared or refreshed '
                    'as drafts. Review the Preview before Apply.',
                )
                return redirect(f'{request.path}?group=MEMORY_EXACT&mode=preview')

            if action == 'adopt_memory':
                memories = adopt_operational_product_memories(
                    source,
                    skus=request.POST.getlist('selected_skus'),
                    approval_note=request.POST.get('notes'),
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    f'{len(memories)} current Calculator solution(s) adopted as approved memory.',
                )
                return self._redirect(request, group_key)

            if action == 'apply_changes':
                if request.POST.get('confirm_apply') != 'yes':
                    raise ProductReconciliationWorkspaceError(
                        'Confirm that you reviewed the Apply plan.'
                    )
                batch = apply_product_reconciliation(
                    source.pk,
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    f'{len(batch["changes"])} Product change(s) applied successfully.',
                )
                return redirect(f'{request.path}?group=ALL_DIFFERENCES')

            if action == 'rollback_apply':
                if request.POST.get('confirm_rollback') != 'yes':
                    raise ProductReconciliationWorkspaceError(
                        'Confirm rollback of the latest Product Apply batch.'
                    )
                batch = rollback_latest_product_apply(
                    source.pk,
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    f'{len(batch["changes"])} Product change(s) restored.',
                )
                return redirect(f'{request.path}?group=ALL_DIFFERENCES&mode=preview')

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
        except (
            ProductReconciliationWorkspaceError,
            ProductReconciliationApplyBlocked,
            ProductReconciliationMemoryError,
        ) as exc:
            messages.error(request, str(exc))
            return self._redirect(request, group_key, edit=request.POST.get('sku', ''))
        raise PermissionDenied('Unsupported reconciliation workspace action.')

    def __call__(self, request, object_id):
        if not self.has_permission(request):
            raise PermissionDenied
        source = self.get_source(request, object_id)
        if request.GET.get('mode') == 'correction' or request.POST.get('correction_action'):
            return self._correction_view(request, source)
        active_apply = has_active_product_apply(source)
        if request.method == 'GET' and self.has_manage_permission(request):
            backfilled = backfill_applied_product_memories(
                source,
                actor=request.user,
                request=request,
            )
            if backfilled:
                messages.info(
                    request,
                    f'{len(backfilled)} previously applied Product decision(s) were '
                    'added to reconciliation memory.',
                )
            prepared = []
            if not active_apply:
                prepared = prepare_exact_memory_drafts(
                    source,
                    actor=request.user,
                    request=request,
                )
            if prepared:
                messages.info(
                    request,
                    f'{len(prepared)} identical previously resolved issue(s) were '
                    'prepared automatically as drafts.',
                )
        rows, summary = build_workspace(source)
        progress = reconciliation_progress(source, rows)
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
            if blocked and request.POST.get('workspace_action') != 'rollback_apply':
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

        apply_plan = build_product_apply_plan(source.pk)
        preview_rows = []
        preview_mode = str(request.GET.get('mode') or '').lower() == 'preview'
        if preview_mode:
            preview_rows = preview_changed_values(apply_plan['items'])

        rules = ProductReconciliationRule.objects.filter(
            client=source.client,
            active=True,
        ).order_by('group_key', 'name')
        navigation_keys = (
            'ALL_DIFFERENCES',
            'SOURCE_DIMENSIONS_ZERO',
            'DIMENSION_UNIT_REVIEW',
            'MEMORY_EXACT',
            'MEMORY_SOURCE_CHANGED',
            'MEMORY_NEW_ISSUE',
            'MEMORY_RULE_MATCH',
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
            'progress': progress,
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
            'can_edit': self.has_manage_permission(request) and not active_apply,
            'active_apply': active_apply,
            'rules': rules,
            'preview_mode': preview_mode,
            'preview_rows': preview_rows,
            'apply_plan': apply_plan,
            'latest_apply_batch': latest_product_apply_batch(source),
        }
        return TemplateResponse(request, self.template_name, context)

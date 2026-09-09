from __future__ import annotations

from django.contrib import messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from apps.imports.models import ExternalDataReviewItem
from apps.imports.services.postcodes_apply import (
    PostcodesApplyBlocked,
    apply_approved_postcodes,
    build_postcodes_apply_plan,
    build_postcodes_rollback_plan,
    postcodes_review_completion,
    rollback_latest_postcodes_apply,
)


class PostcodesApplyAdminMixin:
    def get_urls(self):
        custom = [
            path(
                '<path:object_id>/postcodes-apply/',
                self.admin_site.admin_view(self.postcodes_apply_view),
                name='imports_externaldatafile_postcodes_apply',
            ),
            path(
                '<path:object_id>/postcodes-rollback/',
                self.admin_site.admin_view(self.postcodes_rollback_view),
                name='imports_externaldatafile_postcodes_rollback',
            ),
        ]
        return custom + super().get_urls()

    def _get_postcodes_object(self, request, object_id):
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        if obj.file_type != 'SUBURBS':
            raise Http404
        return obj

    def _postcodes_completion(self, obj):
        if obj is None or obj.file_type != 'SUBURBS':
            return {'completed': False}
        return postcodes_review_completion(obj.pk)

    def get_inline_instances(self, request, obj=None):
        instances = super().get_inline_instances(request, obj)
        completion = self._postcodes_completion(obj)
        if not completion.get('completed'):
            return instances
        return [
            inline
            for inline in instances
            if inline.model is not ExternalDataReviewItem
        ]

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        context = dict(extra_context or {})
        if object_id:
            obj = self.get_object(request, unquote(object_id))
            if obj is not None and obj.file_type == 'SUBURBS':
                completion = self._postcodes_completion(obj)
                context['postcodes_review_completed'] = completion.get(
                    'completed',
                    False,
                )
                context['postcodes_review_completion'] = completion
        return super().changeform_view(
            request,
            object_id,
            form_url,
            extra_context=context,
        )

    def postcodes_apply_view(self, request, object_id):
        obj = self._get_postcodes_object(request, object_id)
        if request.method == 'POST' and request.POST.get('confirm') == 'yes':
            try:
                result = apply_approved_postcodes(
                    obj.pk,
                    actor=request.user,
                    request=request,
                )
            except PostcodesApplyBlocked as exc:
                plan = exc.plan or build_postcodes_apply_plan(obj.pk)
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                self.message_user(
                    request,
                    (
                        'Approved postcode changes applied safely and recorded '
                        'in Audit Events. '
                        f"Batch {result['batch_id']}: "
                        f"{result['change_count']} DB change(s), "
                        f"{result['no_change_count']} already applied/no-change."
                    ),
                    level=messages.SUCCESS,
                )
                return redirect(
                    reverse(
                        'admin:imports_externaldatafile_change',
                        args=[obj.pk],
                    )
                )
        else:
            plan = build_postcodes_apply_plan(obj.pk)

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'original': obj,
            'title': 'Apply approved postcode changes',
            'plan': plan,
            'change_url': reverse(
                'admin:imports_externaldatafile_change',
                args=[obj.pk],
            ),
        }
        return TemplateResponse(
            request,
            'admin/imports/externaldatafile/postcodes_apply_confirm.html',
            context,
        )

    def postcodes_rollback_view(self, request, object_id):
        obj = self._get_postcodes_object(request, object_id)
        if request.method == 'POST' and request.POST.get('confirm') == 'yes':
            try:
                result = rollback_latest_postcodes_apply(
                    obj.pk,
                    actor=request.user,
                    request=request,
                )
            except PostcodesApplyBlocked as exc:
                plan = exc.plan or build_postcodes_rollback_plan(obj.pk)
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                self.message_user(
                    request,
                    (
                        f"Postcode Apply batch {result['batch_id']} rolled back "
                        'safely and recorded in Audit Events.'
                    ),
                    level=messages.SUCCESS,
                )
                return redirect(
                    reverse(
                        'admin:imports_externaldatafile_change',
                        args=[obj.pk],
                    )
                )
        else:
            plan = build_postcodes_rollback_plan(obj.pk)

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'original': obj,
            'title': 'Rollback latest postcode Apply batch',
            'plan': plan,
            'change_url': reverse(
                'admin:imports_externaldatafile_change',
                args=[obj.pk],
            ),
        }
        return TemplateResponse(
            request,
            'admin/imports/externaldatafile/postcodes_rollback_confirm.html',
            context,
        )

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import path, reverse

from apps.clients.models import Client
from apps.imports.services.ftp_inbox import FtpInboxError, scan_ftp_inbox


class FtpInboxAdminMixin:
    def get_urls(self):
        custom_urls = [
            path(
                'check-ftp-inbox/',
                self.admin_site.admin_view(self.check_ftp_inbox_view),
                name='imports_externaldatafile_check_ftp_inbox',
            ),
        ]
        return custom_urls + super().get_urls()

    @staticmethod
    def _ftp_client_from_request(request):
        for key in ('client__id__exact', 'client__exact', 'client'):
            raw = str(request.GET.get(key, '') or request.POST.get(key, '')).strip()
            if not raw:
                continue
            try:
                client_id = int(raw)
            except ValueError as exc:
                raise FtpInboxError('Invalid Client filter.') from exc
            client = Client.objects.filter(pk=client_id, active=True).first()
            if client is None:
                raise FtpInboxError('The selected Client is not active or does not exist.')
            return client

        active_clients = list(Client.objects.filter(active=True).order_by('pk')[:2])
        if len(active_clients) == 1:
            return active_clients[0]
        if not active_clients:
            raise FtpInboxError('There is no active Client available for FTP Inbox.')
        raise FtpInboxError(
            'More than one Client is active. Filter External data files by Client '
            'before using Check FTP Inbox.'
        )

    def changelist_view(self, request, extra_context=None):
        context = dict(extra_context or {})
        context['ftp_inbox_result'] = request.session.pop(
            'ftp_inbox_last_result',
            None,
        )
        return super().changelist_view(request, extra_context=context)

    def check_ftp_inbox_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        changelist_url = reverse('admin:imports_externaldatafile_changelist')
        if request.method != 'POST':
            self.message_user(
                request,
                'Check FTP Inbox must be started from the External data files button.',
                level=messages.INFO,
            )
            return redirect(changelist_url)

        try:
            client = self._ftp_client_from_request(request)
            summary = scan_ftp_inbox(
                client=client,
                actor=request.user,
                request=request,
            )
            request.session['ftp_inbox_last_result'] = summary
        except FtpInboxError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return redirect(changelist_url)

        self.message_user(
            request,
            (
                f'FTP inbox checked for {client.code}: '
                f'{summary["recognised"]} recognised, '
                f'{summary["new_snapshots"]} new snapshot(s), '
                f'{summary["unchanged"]} unchanged, '
                f'{summary["errors"]} error(s). '
                'Review the FTP Inbox details shown below. '
                'No operational freight data was changed.'
            ),
            level=messages.WARNING if summary['errors'] else messages.SUCCESS,
        )
        return redirect(changelist_url)

import json

from django.contrib import admin
from django.utils.html import format_html

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'event_type', 'severity', 'actor', 'client', 'external_file', 'message_short')
    list_filter = ('severity', 'event_type', 'client', 'created_at')
    search_fields = ('event_type', 'message', 'request_id', 'metadata')
    readonly_fields = (
        'actor', 'client', 'external_file', 'event_type', 'severity', 'message',
        'metadata_display', 'ip_address', 'request_id', 'created_at',
    )
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    @admin.display(description='Message')
    def message_short(self, obj):
        return obj.message if len(obj.message) <= 100 else f'{obj.message[:97]}...'

    @admin.display(description='Metadata')
    def metadata_display(self, obj):
        return format_html('<pre style="white-space:pre-wrap">{}</pre>', json.dumps(obj.metadata, indent=2))

    def has_add_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        # Defensive: the admin UI is read-only; events are created by application services.
        if not change:
            return
        super().save_model(request, obj, form, change)

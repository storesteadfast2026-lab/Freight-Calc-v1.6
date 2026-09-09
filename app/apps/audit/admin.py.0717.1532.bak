from django.contrib import admin
from .models import AuditEvent

@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'actor', 'created_at')
    search_fields = ('event_type', 'message')
    readonly_fields = ('created_at',)

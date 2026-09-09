from django.contrib import admin
from .models import ExternalDataFile

@admin.register(ExternalDataFile)
class ExternalDataFileAdmin(admin.ModelAdmin):
    list_display = ('client', 'file_type', 'original_filename', 'status', 'uploaded_at', 'last_imported_at')
    list_filter = ('client', 'file_type', 'status')
    search_fields = ('original_filename', 'stored_path')

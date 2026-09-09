from django.contrib import admin

from .models import SavedEstimate


@admin.register(SavedEstimate)
class SavedEstimateAdmin(admin.ModelAdmin):
    list_display = (
        'reference',
        'client',
        'destination_label',
        'best_estimate_ex_gst',
        'created_by_label',
        'created_at',
    )
    list_filter = ('client', 'created_at', 'schema_version')
    search_fields = (
        'reference',
        'client__code',
        'client__name',
        'created_by_label',
        'destination_label',
    )
    readonly_fields = (
        'reference',
        'client',
        'created_by',
        'created_by_label',
        'schema_version',
        'input_snapshot',
        'result_snapshot',
        'destination_label',
        'total_weight_kg',
        'total_cubic_m3',
        'best_estimate_ex_gst',
        'selected_option_index',
        'created_at',
        'updated_at',
    )

    def has_add_permission(self, request):
        return False


from django.contrib import admin

from .forms import CalculatorUserProfileAdminForm
from .models import CalculatorUserProfile


@admin.register(CalculatorUserProfile)
class CalculatorUserProfileAdmin(admin.ModelAdmin):
    form = CalculatorUserProfileAdminForm
    list_display = (
        'user', 'role', 'client_scope', 'client', 'calculator_access', 'updated_at',
    )
    list_filter = ('role', 'client_scope', 'calculator_access')
    search_fields = ('user__username', 'user__email', 'client__code', 'client__name')
    filter_horizontal = ('allowed_clients',)
    list_select_related = ('user', 'client')
    readonly_fields = ('created_at', 'updated_at')

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

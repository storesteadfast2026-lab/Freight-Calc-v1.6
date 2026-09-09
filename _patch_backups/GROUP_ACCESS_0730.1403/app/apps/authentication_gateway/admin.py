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


# USER_ADMIN_INTEGRATION_0727.0802
from django.contrib.auth import get_user_model as _get_user_model
from django.contrib.auth.admin import UserAdmin as _DjangoUserAdmin
from django.contrib.admin.sites import NotRegistered as _NotRegistered

from .forms import CalculatorUserProfileInlineForm
from .services import DJANGO_ADMINISTRATOR_GROUP


class CalculatorProfileStatusFilter(admin.SimpleListFilter):
    title = 'calculator status'
    parameter_name = 'calculator_status'

    def lookups(self, request, model_admin):
        return (
            ('enabled', 'Enabled'),
            ('disabled', 'Disabled'),
            ('missing', 'Not configured'),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'enabled':
            return queryset.filter(calculator_profile__calculator_access=True)
        if value == 'disabled':
            return queryset.filter(calculator_profile__calculator_access=False)
        if value == 'missing':
            return queryset.filter(calculator_profile__isnull=True)
        return queryset


class CalculatorRoleFilter(admin.SimpleListFilter):
    title = 'calculator role'
    parameter_name = 'calculator_role'

    def lookups(self, request, model_admin):
        return CalculatorUserProfile.Role.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(calculator_profile__role=self.value())
        return queryset


class CalculatorScopeFilter(admin.SimpleListFilter):
    title = 'client scope'
    parameter_name = 'calculator_scope'

    def lookups(self, request, model_admin):
        return CalculatorUserProfile.ClientScope.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(calculator_profile__client_scope=self.value())
        return queryset


class CalculatorUserProfileInline(admin.StackedInline):
    model = CalculatorUserProfile
    form = CalculatorUserProfileInlineForm
    fk_name = 'user'
    extra = 1
    min_num = 0
    max_num = 1
    can_delete = True
    filter_horizontal = ('allowed_clients',)
    verbose_name = 'Calculator access'
    verbose_name_plural = 'Calculator access'
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'calculator_access',
                    'role',
                    'client_scope',
                    'client',
                    'allowed_clients',
                ),
                'description': (
                    'Configure this block only when the account must use the '
                    'Freight Calculator. A Technical Superuser may remain '
                    'without a calculator profile.'
                ),
            },
        ),
        (
            'Record information',
            {
                'classes': ('collapse',),
                'fields': ('created_at', 'updated_at'),
            },
        ),
    )

    def has_add_permission(self, request, obj=None):
        if not request.user.is_active or not request.user.is_superuser:
            return False
        if obj and CalculatorUserProfile.objects.filter(user=obj).exists():
            return False
        return True

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


try:
    admin.site.unregister(CalculatorUserProfile)
except _NotRegistered:
    pass


@admin.register(CalculatorUserProfile)
class HiddenCalculatorUserProfileAdmin(CalculatorUserProfileAdmin):
    """Direct diagnostic view, hidden from the normal Admin menu."""

    def has_module_permission(self, request):
        return False


_User = _get_user_model()
try:
    admin.site.unregister(_User)
except _NotRegistered:
    pass


@admin.register(_User)
class STHUserAdmin(_DjangoUserAdmin):
    """Unified account and calculator-access administration."""

    inlines = (CalculatorUserProfileInline,)
    list_display = (
        'username',
        'email',
        'is_active',
        'calculator_status',
        'calculator_role',
        'calculator_scope',
        'calculator_clients',
        'admin_level',
        'last_login',
    )
    list_display_links = ('username', 'email')
    list_filter = (
        CalculatorProfileStatusFilter,
        CalculatorRoleFilter,
        CalculatorScopeFilter,
        'is_active',
        'is_staff',
        'is_superuser',
    )
    search_fields = (
        'username',
        'email',
        'first_name',
        'last_name',
        'calculator_profile__client__code',
        'calculator_profile__client__name',
        'calculator_profile__allowed_clients__code',
        'calculator_profile__allowed_clients__name',
    )
    ordering = ('username',)
    list_per_page = 50

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related('calculator_profile', 'calculator_profile__client')
            .prefetch_related('calculator_profile__allowed_clients', 'groups')
            .distinct()
        )

    @staticmethod
    def _profile(obj):
        try:
            return obj.calculator_profile
        except CalculatorUserProfile.DoesNotExist:
            return None

    @admin.display(
        description='Calculator status',
        ordering='calculator_profile__calculator_access',
    )
    def calculator_status(self, obj):
        profile = self._profile(obj)
        if profile is None:
            return 'Not configured'
        return 'Enabled' if profile.calculator_access else 'Disabled'

    @admin.display(description='Calculator role', ordering='calculator_profile__role')
    def calculator_role(self, obj):
        profile = self._profile(obj)
        return profile.get_role_display() if profile else '\u2014'

    @admin.display(
        description='Client scope',
        ordering='calculator_profile__client_scope',
    )
    def calculator_scope(self, obj):
        profile = self._profile(obj)
        return profile.get_client_scope_display() if profile else '\u2014'

    @admin.display(description='Client access')
    def calculator_clients(self, obj):
        profile = self._profile(obj)
        if profile is None:
            return '\u2014'
        if profile.role == CalculatorUserProfile.Role.CUSTOMER_USER:
            return profile.client.code if profile.client_id else 'Missing client'
        if profile.client_scope == CalculatorUserProfile.ClientScope.ALL_CLIENTS:
            return 'All active clients'
        clients = list(profile.allowed_clients.all())
        return ', '.join(client.code for client in clients) or 'No clients selected'

    @admin.display(description='Django Admin access', ordering='is_superuser')
    def admin_level(self, obj):
        if obj.is_superuser:
            return 'Technical Superuser'
        if (
            obj.is_staff
            and any(
                group.name == DJANGO_ADMINISTRATOR_GROUP
                for group in obj.groups.all()
            )
        ):
            return 'Django Administrator'
        if obj.is_staff:
            return 'Staff without approved group'
        return 'No Admin access'

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


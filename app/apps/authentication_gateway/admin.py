from django.contrib import admin
from django.utils.html import format_html

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

from .forms import STHUserChangeForm, STHUserCreationForm
from .services import (
    ADMINISTRATORS_GROUP,
    configure_user_from_primary_group,
    primary_access_group_for,
)


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
    """Group-based account and calculator-access administration."""

    form = STHUserChangeForm
    add_form = STHUserCreationForm
    inlines = ()
    fieldsets = (
        (
            'Account',
            {
                'fields': ('username', 'password', 'is_active'),
            },
        ),
        (
            'Personal information',
            {
                'fields': ('first_name', 'last_name', 'email'),
            },
        ),
        (
            'Group-based access',
            {
                'fields': (
                    'primary_access_group',
                    'calculator_client',
                    'effective_access_summary',
                ),
                'description': (
                    'Assign one primary group. Django permissions are managed '
                    'only in Groups; individual user permissions are not available.'
                ),
            },
        ),
        (
            'Important dates',
            {
                'classes': ('collapse',),
                'fields': ('last_login', 'date_joined'),
            },
        ),
    )
    add_fieldsets = (
        (
            'Account',
            {
                'classes': ('wide',),
                'fields': (
                    'username',
                    'email',
                    'first_name',
                    'last_name',
                    'is_active',
                    'primary_access_group',
                    'calculator_client',
                    'password1',
                    'password2',
                ),
            },
        ),
    )
    readonly_fields = ('last_login', 'date_joined', 'effective_access_summary')
    list_display = (
        'username',
        'email',
        'is_active',
        'primary_group',
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

    @admin.display(description='Primary group')
    def primary_group(self, obj):
        if obj.is_superuser:
            return 'Super User'
        try:
            return primary_access_group_for(obj) or 'Not assigned'
        except Exception:
            return 'Conflicting groups'

    @admin.display(description='Django Admin access', ordering='is_superuser')
    def admin_level(self, obj):
        if obj.is_superuser:
            return 'Super User'
        if (
            obj.is_staff
            and any(
                group.name == ADMINISTRATORS_GROUP
                for group in obj.groups.all()
            )
        ):
            return 'Administrator'
        if obj.is_staff:
            return 'Staff without approved group'
        return 'No Admin access'

    @admin.display(description='Effective access')
    def effective_access_summary(self, obj):
        if not obj or not obj.pk:
            return 'Effective access is calculated after the user is saved.'
        if obj.is_superuser:
            return format_html(
                '<strong>Super User</strong><br>'
                'Django Admin: full access<br>'
                'Calculator access: optional profile<br>'
                'Permissions source: Django is_superuser'
            )

        group_name = self.primary_group(obj)
        profile = self._profile(obj)
        calculator_access = (
            'Enabled' if profile and profile.calculator_access else 'Not configured'
        )
        client_access = self.calculator_clients(obj)
        admin_access = (
            'Operational Django Admin'
            if group_name == ADMINISTRATORS_GROUP
            else 'No Django Admin access'
        )
        return format_html(
            '<strong>{}</strong><br>'
            'Calculator access: {}<br>'
            'Client access: {}<br>'
            'Django Admin: {}<br>'
            'Individual permissions: disabled',
            group_name,
            calculator_access,
            client_access,
            admin_access,
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.is_superuser:
            return
        configure_user_from_primary_group(
            obj,
            form.cleaned_data['primary_access_group'],
            form.cleaned_data.get('calculator_client'),
        )

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


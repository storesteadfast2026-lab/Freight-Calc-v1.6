from django.contrib import admin
from django.core.exceptions import PermissionDenied
from apps.authentication_gateway.services import allowed_clients_for, CalculatorAccessDenied
from .models import Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('client', 'sku', 'name', 'freight_type', 'weight_kg', 'cubic_m3', 'active')
    list_filter = ('client', 'freight_type', 'active')
    search_fields = ('sku', 'name', 'description')

    def _clients(self, request):
        if request.user.is_superuser:
            from apps.clients.models import Client
            return Client.objects.filter(active=True)
        try:
            return allowed_clients_for(request.user)
        except CalculatorAccessDenied:
            from apps.clients.models import Client
            return Client.objects.none()

    def get_queryset(self, request):
        return super().get_queryset(request).filter(client__in=self._clients(request))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'client':
            kwargs['queryset'] = self._clients(request)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not self._clients(request).filter(pk=obj.client_id).exists():
            raise PermissionDenied('This Client is not authorised for the current user.')
        super().save_model(request, obj, form, change)

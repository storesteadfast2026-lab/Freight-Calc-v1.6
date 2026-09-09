from django.contrib import admin
from .models import Carrier, CarrierService, ClientCarrierConfig

@admin.register(Carrier)
class CarrierAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'active')
    search_fields = ('code', 'name')

@admin.register(CarrierService)
class CarrierServiceAdmin(admin.ModelAdmin):
    list_display = ('carrier', 'service_code', 'service_name', 'active')
    list_filter = ('carrier', 'active')

@admin.register(ClientCarrierConfig)
class ClientCarrierConfigAdmin(admin.ModelAdmin):
    list_display = ('client', 'carrier_service', 'base_status', 'customer_code', 'fuel_levy', 'cubic_conversion', 'tailgate_enabled', 'pallet_enabled', 'carton_enabled', 'active')
    list_filter = ('client', 'active', 'base_status', 'tailgate_enabled', 'pallet_enabled', 'carton_enabled', 'zone_enabled', 'postcode_zones_enabled')
    search_fields = ('carrier_service__carrier__code', 'carrier_service__service_code', 'ratecard')

from django.contrib import admin
from .models import FreightZone, FreightRate, CarrierTailgateCharge

@admin.register(FreightZone)
class FreightZoneAdmin(admin.ModelAdmin):
    list_display = ('client', 'carrier_service', 'suburb', 'state', 'postcode', 'zone', 'subzone', 'area')
    list_filter = ('client', 'state', 'carrier_service')
    search_fields = ('suburb', 'postcode', 'zone')

@admin.register(FreightRate)
class FreightRateAdmin(admin.ModelAdmin):
    list_display = ('client', 'carrier_service', 'zone', 'subzone', 'area', 'weight_break', 'freight_type', 'minimum_charge', 'basic_charge')
    list_filter = ('client', 'carrier_service', 'zone', 'freight_type')
    search_fields = ('lookup_key', 'zone', 'area')

@admin.register(CarrierTailgateCharge)
class CarrierTailgateChargeAdmin(admin.ModelAdmin):
    list_display = ('client', 'carrier', 'minimum_charge', 'per_subsequent_charge', 'hand_unload_charge')
    list_filter = ('client', 'carrier')

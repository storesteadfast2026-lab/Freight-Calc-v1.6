from django.contrib import admin
from .models import Client, FreightCalculator

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'active', 'updated_at')
    search_fields = ('code', 'name')

@admin.register(FreightCalculator)
class FreightCalculatorAdmin(admin.ModelAdmin):
    list_display = ('client', 'name', 'version', 'calculation_engine_key', 'active')
    list_filter = ('client', 'active')

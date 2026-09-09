from django.contrib import admin
from .models import Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('client', 'sku', 'name', 'freight_type', 'weight_kg', 'cubic_m3', 'active')
    list_filter = ('client', 'freight_type', 'active')
    search_fields = ('sku', 'name', 'description')

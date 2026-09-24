from django.contrib import admin
from .models import Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('client', 'customer_code', 'sku', 'name', 'freight_type', 'weight_kg', 'cubic_m3', 'active')
    list_filter = ('client', 'customer_code', 'freight_type', 'active')
    search_fields = ('customer_code', 'sku', 'name', 'description')

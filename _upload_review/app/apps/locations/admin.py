from django.contrib import admin
from .models import FromAddress, Suburb

@admin.register(FromAddress)
class FromAddressAdmin(admin.ModelAdmin):
    list_display = ('client', 'name', 'suburb', 'state', 'postcode', 'is_default', 'active')
    list_filter = ('client', 'state', 'active')
    search_fields = ('name', 'suburb', 'postcode')

@admin.register(Suburb)
class SuburbAdmin(admin.ModelAdmin):
    list_display = ('suburb_name', 'state', 'postcode')
    search_fields = ('suburb_name', 'state', 'postcode')

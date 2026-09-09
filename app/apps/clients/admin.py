from django.contrib import admin

from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "active", "updated_at")
    search_fields = ("code", "name")

"""Admin registrations for the example payments app."""

from django.contrib import admin

from .models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Admin for orders with the payment lifecycle fields."""

    list_display = ("order_id", "gateway", "amount", "status", "provider_ref", "updated_at")
    list_filter = ("gateway", "status")
    search_fields = ("order_id", "provider_ref", "lookup_ref")
    readonly_fields = ("created_at", "updated_at")

"""App configuration for the example payments app."""

from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    """Example app wiring for the payment gateways."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"

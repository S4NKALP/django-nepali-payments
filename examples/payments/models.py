"""Order model used to demonstrate the payment gateways in a Django app."""

from django.db import models
from django.utils import timezone


class Order(models.Model):
    """A minimal order that gets paid through one of the gateways.

    Status values mirror the gateway lifecycle observed through
    ``initiate_payment`` / ``verify_payment``:
    ``pending``, ``initiated``, ``paid``, ``failed``, ``cancelled``, ``timeout``.
    A paid settlement whose amount does not match the order is still stored as
    ``failed``, with ``payment_data["amount_mismatch"]`` set to ``True``.
    """

    class Meta:
        verbose_name = "order"
        verbose_name_plural = "orders"

    gateway = models.CharField(max_length=32, help_text="Khalti, eSewa or Fonepay")
    order_id = models.CharField(max_length=64, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255, blank=True, default="")

    status = models.CharField(max_length=16, default="pending")
    provider_ref = models.CharField(max_length=255, blank=True, default="")

    #: Raw provider reference handed back for verification (e.g. Khalti pidx).
    lookup_ref = models.CharField(max_length=512, blank=True, default="")
    #: Last verification payload, keyed by field name.
    payment_data = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        """Return a short human-readable representation of the order."""
        return f"{self.order_id} ({self.gateway}, {self.status})"

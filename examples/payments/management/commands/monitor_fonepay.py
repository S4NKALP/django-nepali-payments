"""Management command running the Fonepay QR status monitor.

In a shared-hosting-friendly setup the polling monitor runs as a background
worker rather than inside the HTTP request path. This command:

1. Scans for Fonepay orders still in the ``initiated`` state.
2. Starts the :class:`FonepayPaymentMonitor` for each order's PRN.
3. Persists the outcome to the database when a payment verifies, fails,
   times out or errors.

Run it with::

    python manage.py monitor_fonepay
"""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from nepali_payment import FonepayPaymentMonitor, PaymentCredentials
from payments.models import Order

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Run the Fonepay status monitor until interrupted."""

    help = "Poll Fonepay for payment settlements on initiated QR orders."

    def handle(self, *args: object, **options: object) -> None:
        """Start monitoring and block until Ctrl-C."""
        monitor = FonepayPaymentMonitor(
            timeout=settings.FONEPAY_MONITOR_TIMEOUT,
            interval=settings.FONEPAY_MONITOR_INTERVAL,
        )

        monitor.on("verified")(lambda args: self._on_verified(monitor, args.prn, args.success))
        monitor.on("timeout")(lambda args: self._on_timeout(monitor, args.prn))
        monitor.on("error")(lambda args: self._on_error(args.prn, args.error_message))

        pending = Order.objects.filter(gateway="fonepay", status="initiated")
        started = 0
        for order in pending:
            monitor.start(
                order.order_id,
                PaymentCredentials(
                    secret_key=settings.FONEPAY_SECRET,
                    merchant_code=settings.FONEPAY_MERCHANT,
                    username=settings.FONEPAY_USERNAME,
                    password=settings.FONEPAY_PASSWORD,
                    sandbox_mode=settings.PAID_MODE.lower() == "sandbox",
                ),
            )
            started += 1

        self.stdout.write(self.style.SUCCESS(f"Monitoring {started} initiated Fonepay order(s). Press Ctrl-C to stop."))

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Stopping monitor...")
        finally:
            monitor.dispose()

    def _on_verified(self, monitor: FonepayPaymentMonitor, prn: str, success: bool) -> None:
        Order.objects.filter(order_id=prn).update(status="paid" if success else "failed", updated_at=timezone.now())
        self.stdout.write(self.style.SUCCESS(f"prn={prn} verified success={success}"))
        monitor.stop(prn)

    def _on_timeout(self, monitor: FonepayPaymentMonitor, prn: str) -> None:
        Order.objects.filter(order_id=prn).update(status="timeout", updated_at=timezone.now())
        self.stdout.write(self.style.WARNING(f"prn={prn} timed out"))
        monitor.stop(prn)

    def _on_error(self, prn: str, message: str) -> None:
        logger.error("prn=%s polling error: %s", prn, message)

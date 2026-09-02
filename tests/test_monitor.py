"""Fonepay payment-status polling monitor tests (constitution II / IV).

The monitor polls Fonepay's QR status endpoint over plain HTTP, so it works on
shared hosting without persistent sockets or an async event loop. These tests
drive the polling loop with a short interval/timeout and a stubbed status
source to keep them fast and deterministic.
"""

import threading
import time
from datetime import timedelta

from nepali_payment.models.fonepay import QrStatusResponse
from nepali_payment.monitor import (
    FonepayPaymentMonitor,
    PaymentCredentials,
    _normalise_status,
)


class TestStatusNormalisation:
    def test_success_statuses_map_to_payment_success(self):
        for status in ("Complete", "Completed", "Paid", "SUCCESS", "success"):
            assert _normalise_status(status) == "payment_success"

    def test_failure_statuses_map_to_payment_failed(self):
        assert _normalise_status("FAILED") == "payment_failed"
        assert _normalise_status("Payment Error") == "payment_failed"

    def test_cancelled_status_maps_to_payment_cancelled(self):
        assert _normalise_status("Cancelled") == "payment_cancelled"

    def test_pending_status_maps_to_qr_verified(self):
        assert _normalise_status("Pending") == "qr_verified"

    def test_unknown_status_passes_through(self):
        assert _normalise_status("SomeCustom") == "SomeCustom"


class TestFonepayPaymentMonitor:
    def _make_monitor(self, **kwargs):
        monitor = FonepayPaymentMonitor(
            timeout=timedelta(milliseconds=200), interval=timedelta(milliseconds=20), **kwargs
        )
        return monitor

    def test_poll_emits_verified_on_success(self):
        monitor = self._make_monitor(api=None)
        verified = []
        monitor.on("verified")(lambda a: verified.append(a))

        def fake_poll_once(prn):
            return QrStatusResponse(fonepay_trace_id=1, payment_status="Paid", prn=prn)

        monitor._poll_once = fake_poll_once  # type: ignore[method-assign]
        monitor._poll_loop("prn-1", MonitorStopEvent())

        assert len(verified) == 1
        assert verified[0].success is True
        assert verified[0].prn == "prn-1"

    def test_poll_emits_status_then_timeout_when_not_settled(self):
        monitor = self._make_monitor(api=None)
        statuses = []
        timeouts = []
        monitor.on("status")(lambda a: statuses.append(a))
        monitor.on("timeout")(lambda a: timeouts.append(a))

        def fake_poll_once(prn):
            return QrStatusResponse(fonepay_trace_id=1, payment_status="Pending", prn=prn)

        monitor._poll_once = fake_poll_once  # type: ignore[method-assign]
        monitor._poll_loop("prn-1", MonitorStopEvent())

        assert any(s.payment_status == "qr_verified" for s in statuses)
        assert len(timeouts) == 1

    def test_poll_reports_error_from_failed_status_check(self):
        monitor = self._make_monitor(api=None)
        errors = []
        monitor.on("error")(lambda a: errors.append(a))

        def fake_poll_once(prn):
            raise RuntimeError("status check failed")

        monitor._poll_once = fake_poll_once  # type: ignore[method-assign]
        # Small timeout so the loop fails once, then breaks on timeout.
        monitor._timeout = timedelta(milliseconds=50)
        monitor._poll_loop("prn-1", MonitorStopEvent())

        assert len(errors) >= 1

    def test_start_and_is_monitoring_lifecycle(self):
        monitor = self._make_monitor(api=None)
        monitor.start("prn-1", PaymentCredentials(secret_key="k", merchant_code="NBQM", username="u", password="p"))
        assert monitor.is_monitoring("prn-1")
        monitor.stop("prn-1")
        assert not monitor.is_monitoring("prn-1")

    def test_dispose_stops_all(self):
        monitor = self._make_monitor(api=None)
        monitor.start("prn-1", PaymentCredentials(secret_key="k", merchant_code="NBQM", username="u", password="p"))
        monitor.start("prn-2", PaymentCredentials(secret_key="k", merchant_code="NBQM", username="u", password="p"))
        monitor.dispose()
        assert not monitor.is_monitoring("prn-1")
        assert not monitor.is_monitoring("prn-2")

    def test_terminal_event_cleans_up_state(self):
        """A terminal (verified) event must release the PRN's credentials and
        cached manager to avoid a leak of monitor bookkeeping."""
        monitor = self._make_monitor(api=None)
        creds = PaymentCredentials(secret_key="k", merchant_code="NBQM", username="u", password="p")
        with monitor._lock:
            monitor._credentials["prn-1"] = creds
            monitor._managers["prn-1"] = object()  # fake cached manager
            monitor._threads["prn-1"] = threading.current_thread()
            monitor._stop_events["prn-1"] = threading.Event()

        def fake_poll_once(prn):
            return QrStatusResponse(fonepay_trace_id=1, payment_status="Paid", prn=prn)

        monitor._poll_once = fake_poll_once  # type: ignore[method-assign]
        monitor._poll_loop("prn-1", MonitorStopEvent())

        with monitor._lock:
            assert "prn-1" not in monitor._credentials
            assert "prn-1" not in monitor._managers
            assert "prn-1" not in monitor._threads
            assert "prn-1" not in monitor._stop_events

    def test_accepts_numeric_seconds_for_timeout_and_interval(self):
        """Neither timeout nor interval must require a timedelta; plain seconds
        (int/float) are a valid, user-friendly alternative."""
        monitor = FonepayPaymentMonitor(timeout=5, interval=0.5)
        assert monitor._timeout == timedelta(seconds=5)
        assert monitor._interval == timedelta(seconds=0.5)


class MonitorStopEvent:
    """A stop event that is already set so the poll loop exits quickly."""

    def is_set(self):
        return False

    def wait(self, timeout=None):
        time.sleep(0.001)
        return False

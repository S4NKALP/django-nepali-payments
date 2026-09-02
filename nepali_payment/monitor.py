"""Fonepay payment-status monitor.

A :class:`FonepayPaymentMonitor` can watch several payments at once. For each
one (identified by a Payment Reference Number, or PRN) a background thread asks
Fonepay for the current status every few seconds, until the payment finishes or
the timeout runs out.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from nepali_payment.enums import PaymentMethod, PaymentMode
from nepali_payment.http import ApiService
from nepali_payment.manager import PaymentManager
from nepali_payment.models import PaymentResult
from nepali_payment.models.fonepay import QrStatusResponse

#: PRN is treated as verified when Fonepay reports one of these status strings.
_VERIFIED_STATUSES = {
    "Complete",
    "Completed",
    "Paid",
    "SUCCESS",
    "success",
}


def _to_timedelta(value: Any) -> timedelta:
    """Turn a ``timedelta`` or a plain number of seconds into a ``timedelta``."""
    if isinstance(value, timedelta):
        return value
    return timedelta(seconds=float(value))


@dataclass
class PaymentStatusEventArgs:
    """Payload delivered to ``status`` handlers."""

    prn: str
    payment_status: str = ""
    qr_verified: bool | None = None
    payment_success: bool | None = None
    raw_message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    additional_data: dict[str, Any] | None = None


@dataclass
class PaymentTimeoutEventArgs:
    """Payload delivered to ``timeout`` handlers."""

    prn: str
    timeout_duration: timedelta
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PaymentErrorEventArgs:
    """Payload delivered to ``error`` handlers."""

    prn: str
    error_message: str = ""
    exception: Exception | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PaymentVerifiedEventArgs:
    """Payload delivered to ``verified`` handlers."""

    prn: str
    success: bool
    verification_data: dict[str, Any] | None = None
    error_message: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PaymentCancelledEventArgs:
    """Payload delivered to ``cancelled`` handlers."""

    prn: str
    reason: str = ""
    cancelled_by: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PaymentCredentials:
    """Provider credentials required to query Fonepay status."""

    secret_key: str
    merchant_code: str
    username: str
    password: str
    sandbox_mode: bool = False


class FonepayPaymentMonitor:
    """Keep checking Fonepay until a payment finishes.

    Works fine on shared hosting - it does not hold any open connections. Each
    payment gets its own small background thread. When the status changes or the
    payment settles, it fires ``status``, ``verified``, ``timeout`` or ``error``
    events that you can listen to.
    """

    #: Default overall session lifetime before a ``timeout`` event fires.
    DEFAULT_TIMEOUT = timedelta(minutes=15)
    #: Default delay between status polls.
    DEFAULT_INTERVAL = timedelta(seconds=5)

    def __init__(
        self,
        api: ApiService | None = None,
        timeout: timedelta = DEFAULT_TIMEOUT,
        interval: timedelta = DEFAULT_INTERVAL,
    ) -> None:
        """Initialise a monitor.

        Args:
            api: Your own HTTP client (optional). If left out, a new one is made.
            timeout: How long to keep checking before firing a ``timeout``
                event. Pass a ``timedelta`` or a number of seconds.
            interval: How long to wait between each status check. Pass a
                ``timedelta`` or a number of seconds.

        """
        self._api = api if api is not None else ApiService()
        self._timeout = _to_timedelta(timeout)
        self._interval = _to_timedelta(interval)

        self.status_changed: list[Callable[[PaymentStatusEventArgs], None]] = []
        self.payment_verified: list[Callable[[PaymentVerifiedEventArgs], None]] = []
        self.payment_timeout: list[Callable[[PaymentTimeoutEventArgs], None]] = []
        self.payment_error: list[Callable[[PaymentErrorEventArgs], None]] = []
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._credentials: dict[str, PaymentCredentials] = {}
        self._managers: dict[str, PaymentManager] = {}
        self._lock = threading.Lock()

    #  events

    def on(self, event: str) -> Callable[[Callable], Callable]:
        """Register a handler for an event name.

        Supported events: ``status``, ``verified``, ``timeout``, ``error``.

        Returns the original callable so it can also be used directly.
        """

        def wrap(func: Callable) -> Callable:
            self._register(event, func)
            return func

        return wrap

    def _register(self, event: str, handler: Callable) -> None:
        event_map: dict[str, list] = {
            "status": self.status_changed,
            "verified": self.payment_verified,
            "timeout": self.payment_timeout,
            "error": self.payment_error,
        }
        targets = event_map.get(event)
        if targets is not None:
            targets.append(handler)

    def _emit(self, event: str, args: Any) -> None:
        """Dispatch an event to every registered handler, isolating failures."""
        handlers: dict[str, list[Callable]] = {
            "status": self.status_changed,
            "verified": self.payment_verified,
            "timeout": self.payment_timeout,
            "error": self.payment_error,
        }
        for handler in handlers.get(event, []):
            try:
                handler(args)
            except Exception:  # noqa: BLE001, S112  # one handler must not break the others
                continue

    # lifecycle

    def start(
        self,
        prn: str,
        credentials: PaymentCredentials,
    ) -> None:
        """Begin polling a PRN in a background thread.

        Args:
            prn: The payment reference number to monitor.
            credentials: Fonepay credentials used to verify status.

        """
        if not prn or credentials is None:
            return
        self.stop(prn)

        mode = PaymentMode.SANDBOX if credentials.sandbox_mode else PaymentMode.PRODUCTION
        manager = PaymentManager(
            PaymentMethod.FONEPAY,
            mode,
            credentials.secret_key,
            api=self._api,
        )

        stop_event = threading.Event()
        with self._lock:
            self._stop_events[prn] = stop_event
            self._credentials[prn] = credentials
            self._managers[prn] = manager

        thread = threading.Thread(
            target=self._poll_loop,
            args=(prn, stop_event),
            name=f"fonepay-monitor-{prn}",
            daemon=True,
        )
        with self._lock:
            self._threads[prn] = thread
        thread.start()

    def stop(self, prn: str) -> None:
        """Signal a PRN's poller to stop and wait for it to finish."""
        with self._lock:
            stop_event = self._stop_events.pop(prn, None)
            thread = self._threads.pop(prn, None)
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._interval.total_seconds() + 1)
        with self._lock:
            self._credentials.pop(prn, None)
            self._managers.pop(prn, None)

    def is_monitoring(self, prn: str) -> bool:
        """Return whether ``prn`` currently has an active, running poller."""
        with self._lock:
            thread = self._threads.get(prn)
        return thread is not None and thread.is_alive()

    def dispose(self) -> None:
        """Stop every active poller and release the shared HTTP session."""
        prns = list(self._threads.keys())
        for prn in prns:
            self.stop(prn)
        self._api.close()
        with self._lock:
            self._threads.clear()
            self._stop_events.clear()
            self._credentials.clear()
            self._managers.clear()

    #  internals

    def _poll_loop(self, prn: str, stop_event: threading.Event) -> None:
        """Keep polling the status until the payment settles, is stopped or times out."""
        started = time.monotonic()
        last_status: str | None = None

        while not stop_event.is_set():
            elapsed = timedelta(seconds=time.monotonic() - started)
            if elapsed >= self._timeout:
                self._emit(
                    "timeout",
                    PaymentTimeoutEventArgs(prn=prn, timeout_duration=self._timeout),
                )
                break

            try:
                status = self._poll_once(prn)
            except Exception as exc:  # noqa: BLE001  # transient network/provider errors surface as events
                self._emit(
                    "error",
                    PaymentErrorEventArgs(prn=prn, error_message=str(exc), exception=exc),
                )
                status = None

            if status is not None and status.payment_status:
                status_text = status.payment_status
                if status_text != last_status:
                    last_status = status_text
                    normalised = _normalise_status(status_text)
                    event_args = PaymentStatusEventArgs(prn=prn, payment_status=normalised, raw_message=status_text)
                    self._emit("status", event_args)

                    if normalised == "payment_success":
                        self._emit(
                            "verified",
                            PaymentVerifiedEventArgs(prn=prn, success=True, verification_data=status.__dict__),
                        )
                        break
                    if normalised in {"payment_failed", "payment_cancelled"}:
                        self._emit(
                            "verified",
                            PaymentVerifiedEventArgs(prn=prn, success=False, verification_data=status.__dict__),
                        )
                        break

            stop_event.wait(self._interval.total_seconds())

        with self._lock:
            self._threads.pop(prn, None)
            self._stop_events.pop(prn, None)
            self._credentials.pop(prn, None)
            self._managers.pop(prn, None)

    def _poll_once(self, prn: str) -> QrStatusResponse:
        """Do one status check and return what Fonepay said."""
        with self._lock:
            credentials = self._credentials.get(prn)
            manager = self._managers.get(prn)
        if credentials is None or manager is None:
            raise RuntimeError("Payment credentials not found for polling")

        verification_data = {
            "prn": prn,
            "merchantCode": credentials.merchant_code,
            "username": credentials.username,
            "password": credentials.password,
        }
        result: PaymentResult = manager.verify_payment(PaymentResult, json.dumps(verification_data))
        if not result.success:
            raise RuntimeError(result.message or "Fonepay status check failed")
        return result.data  # type: ignore[return-value]


def _normalise_status(status: str) -> str:
    """Translate Fonepay's status words into our own standard ones."""
    if status in _VERIFIED_STATUSES:
        return "payment_success"
    lowered = status.lower()
    if "fail" in lowered or "error" in lowered:
        return "payment_failed"
    if "cancel" in lowered:
        return "payment_cancelled"
    if "accountholdername" in lowered or "pending" in lowered or "active" in lowered:
        return "qr_verified"
    return status

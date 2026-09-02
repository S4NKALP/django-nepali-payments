"""Base class shared by all payment services.

Every gateway (Khalti, eSewa, Fonepay, ConnectIPS) has its own service file.
All of them inherit from :class:`BasePaymentService`. This base class stores the
things that are the same for every gateway: the HTTP client, the API base URL,
and a helper that catches errors and turns them into a failed result.
"""

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from nepali_payment.constants import ApiEndpoints
from nepali_payment.enums import PaymentMode
from nepali_payment.helpers import convert_to
from nepali_payment.http import ApiService
from nepali_payment.models import PaymentResult

T = TypeVar("T")


class BasePaymentService(ABC):
    """Common behaviour for gateway services.

    Subclasses must write your own ``initiate_payment`` and ``verify_payment``.
    Most gateways (Khalti, Fonepay, ConnectIPS) wrap their code with
    :meth:`_run_result` so any error becomes a failed ``PaymentResult`` instead
    of crashing. eSewa is different - it raises ``PaymentError`` straight away.
    """

    #: Gateway ``ApiEndpoints`` grouping providing ``*_BASE_URL`` and
    #: ``SANDBOX_*_BASE_URL``. Overridden by each concrete service.
    _api: type = ApiEndpoints

    def __init__(self, payment_mode: PaymentMode, api: ApiService | None = None):
        """Create a base service.

        Args:
            payment_mode: ``SANDBOX`` or ``PRODUCTION``. This chooses which API
                address to talk to.
            api: Your own HTTP client (optional). If you leave it out, a new one
                is made for you.

        """
        self._payment_mode = payment_mode
        self._api_service = api if api is not None else ApiService()

    @property
    def base_url(self) -> str:
        """Pick the base API address for the active mode."""
        if self._payment_mode == PaymentMode.PRODUCTION:
            return self._api.BASE_URL
        return self._api.SANDBOX_BASE_URL

    @abstractmethod
    def initiate_payment(self, result_cls: type[T], content: Any) -> T:
        """Start a payment. Returns a typed result."""

    @abstractmethod
    def verify_payment(self, result_cls: type[T], content: Any) -> T:
        """Check whether a payment really went through. Returns a typed result."""

    def _as_failed(self, result_cls: type[T], exc: Exception) -> T:
        """Turn an error ``exc`` into a failed result."""
        return convert_to(result_cls, PaymentResult(success=False, message=str(exc)))

    def _run_result(self, result_cls: type[T], body: Any) -> T:
        """Run ``body`` and catch any error so it becomes a failed result.

        This is the default behaviour for Khalti, Fonepay and ConnectIPS: rather
        than letting the error crash the program, we package it into a
        ``result_cls`` that says the payment failed.

        Args:
            result_cls: The shape the result should be turned into.
            body: A function with no arguments that returns a ``PaymentResult``.

        Returns:
            The result from ``body()`` if it works; otherwise a failed result
            that wraps the error.

        """
        try:
            return body()
        except Exception as exc:  # noqa: BLE001  # fold any failure into a failed result
            return self._as_failed(result_cls, exc)

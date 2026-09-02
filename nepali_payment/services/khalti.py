"""Khalti payment service."""

from typing import Any, TypeVar

from nepali_payment.constants import ApiEndpoints
from nepali_payment.enums import PaymentAction, PaymentMethod, PaymentMode
from nepali_payment.factory import _endpoint_for
from nepali_payment.helpers import convert_to
from nepali_payment.http import ApiService
from nepali_payment.models import PaymentResult
from nepali_payment.models.khalti import PaymentResponse, RequestResponse
from nepali_payment.services.base import BasePaymentService

T = TypeVar("T")


class PaymentService(BasePaymentService):
    """Khalti integration.

    To call Khalti we send an ``Authorization: key <secret>`` header. Starting a
    payment sends JSON; checking a payment sends form data that includes the
    ``pidx``. If something goes wrong, the error becomes a failed
    ``PaymentResult`` instead of crashing.
    """

    _api = ApiEndpoints.KHALTI

    def __init__(self, secret_key: str, payment_mode: PaymentMode, api: ApiService | None = None):
        """Create a Khalti service.

        Args:
            secret_key: Khalti's secret key (sandbox or live).
            payment_mode: ``SANDBOX`` or ``PRODUCTION``.
            api: Your own HTTP client (optional). If left out, a new one is made.

        """
        if not secret_key:
            raise ValueError("Secret key cannot be null or empty.")
        self._secret_key = secret_key
        super().__init__(payment_mode, api)

    def initiate_payment(self, result_cls: type[T], content: Any) -> T:
        """Start a Khalti payment."""

        def _call() -> T:
            api_url, http_method = _endpoint_for(
                PaymentMethod.KHALTI, PaymentAction.PROCESS_PAYMENT, self._payment_mode
            )
            headers = {"Authorization": f"key {self._secret_key}"}
            response = self._api_service.get_async_result(
                RequestResponse,
                api_url,
                http_method,
                header_param=headers,
                request_body=content,
            )
            result = PaymentResult(data=response, success=True, message="Payment initiated successfully")
            return convert_to(result_cls, result)

        return self._run_result(result_cls, _call)

    def verify_payment(self, result_cls: type[T], content: str) -> T:
        """Verify a Khalti payment by pidx."""

        def _call() -> T:
            api_url, http_method = _endpoint_for(PaymentMethod.KHALTI, PaymentAction.VERIFY_PAYMENT, self._payment_mode)
            headers = {"Authorization": f"key {self._secret_key}"}
            form_content = {"pidx": content}
            response = self._api_service.get_async_result(
                PaymentResponse,
                api_url,
                http_method,
                header_param=headers,
                key_value_pairs=form_content,
            )
            result = PaymentResult(data=response, success=True, message="Payment verified successfully")
            return convert_to(result_cls, result)

        return self._run_result(result_cls, _call)

"""
ConnectIPS payment service.
To start a payment, ConnectIPS sends the customer to a bank sign-in form.
We also check the payment afterwards by validating a signed token.
"""

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from nepali_payment.constants import ApiEndpoints
from nepali_payment.enums import PaymentMode
from nepali_payment.exceptions import ProviderError, ValidationError
from nepali_payment.helpers import convert_to, generate_rsa_signature, load_rsa_private_key
from nepali_payment.http import ApiService
from nepali_payment.models import PaymentResult
from nepali_payment.models.connectips import (
    FormResponse,
    PaymentRequest,
    VerificationRequest,
    VerificationResponse,
)
from nepali_payment.services.base import BasePaymentService

T = TypeVar("T")

STATUS_SUCCESS = "SUCCESS"
STATUS_PENDING = "PENDING"
STATUS_CANCELLED = "CANCELLED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_SESSION_EXPIRED = "SESSION_EXPIRED"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_INVALID_TOKEN = "INVALID_TOKEN"

_STATUS_COMPLETE = "COMPLETE"
_STATUS_PENDING = "PENDING"
_STATUS_CANCELLED = "CANCELLED"
_STATUS_EXPIRED = "EXPIRED"
_STATUS_FAILED = "FAILED"


def normalize_status(status: str | None) -> str:
    """Translate ConnectIPS's status words into our own standard ones."""
    normalized = (status or "").upper()
    if normalized == STATUS_SUCCESS:
        return _STATUS_COMPLETE
    if normalized == STATUS_PENDING:
        return _STATUS_PENDING
    if normalized == STATUS_CANCELLED:
        return _STATUS_CANCELLED
    if normalized in (STATUS_TIMEOUT, STATUS_SESSION_EXPIRED):
        return _STATUS_EXPIRED
    return _STATUS_FAILED


@dataclass
class ConnectIpsConfig:
    """Merchant credentials and endpoints to run a ConnectIPS service."""

    merchant_id: str = ""
    app_id: str = ""
    app_name: str = ""
    app_password: str = ""
    cert_path: str | None = None
    cert_data: bytes | None = None
    cert_format: str | None = None
    cert_password: str | None = None
    success_url: str | None = None
    failure_url: str | None = None
    timeout: float = 30.0
    _private_key: Any = field(default=None, repr=False, compare=False)


class PaymentService(BasePaymentService):
    """ConnectIPS integration.

    Starting a payment builds the hidden form fields the customer posts to the
    bank's sign-in page. Verifying signs a token and asks ConnectIPS whether the
    transaction went through. Errors become a failed ``PaymentResult``.
    """

    _api = ApiEndpoints.CONNECTIPS

    def __init__(
        self,
        config: ConnectIpsConfig,
        payment_mode: PaymentMode,
        api: ApiService | None = None,
    ):
        """Create a ConnectIPS service.

        Args:
            config: ConnectIPS merchant credentials and certificate.
            payment_mode: ``SANDBOX`` or ``PRODUCTION``.
            api: Your own HTTP client (optional). If left out, a new one is made.

        Raises:
            ValidationError: If required config fields or the certificate are missing.

        """
        if not config.merchant_id:
            raise ValidationError("merchant_id is required for ConnectIPS.")
        if not config.app_id:
            raise ValidationError("app_id is required for ConnectIPS.")
        if config.cert_path is None and not config.cert_data and config._private_key is None:
            raise ValidationError("cert_path, cert_data or a private key is required for ConnectIPS.")
        if config._private_key is not None:
            private_key = config._private_key
        else:
            private_key = load_rsa_private_key(
                cert_path=config.cert_path,
                cert_data=config.cert_data,
                cert_format=config.cert_format,
                cert_password=config.cert_password,
            )
        self._config = config
        self._private_key = private_key
        super().__init__(payment_mode, api)

    @property
    def _login_url(self) -> str:
        if self._payment_mode == PaymentMode.SANDBOX:
            return ApiEndpoints.CONNECTIPS.SANDBOX_LOGIN_URL
        return ApiEndpoints.CONNECTIPS.LOGIN_URL

    @property
    def _validation_url(self) -> str:
        if self._payment_mode == PaymentMode.SANDBOX:
            return ApiEndpoints.CONNECTIPS.SANDBOX_VALIDATION_URL
        return ApiEndpoints.CONNECTIPS.VALIDATION_URL

    def initiate_payment(self, result_cls: type[T], content: Any) -> T:
        """Build the ConnectIPS form fields for a payment.

        Args:
            result_cls: The shape the result should be turned into.
            content: A :class:`~nepali_payment.models.connectips.PaymentRequest`.

        Returns:
            A ``result_cls`` wrapping the form (``target_url`` and the
            ``form_fields`` to POST).

        Raises:
            TypeError: If ``content`` is not a PaymentRequest.

        """
        if not isinstance(content, PaymentRequest):
            raise TypeError("Content must be of type PaymentRequest")

        def _call() -> T:
            self._validate_initiate(content)
            txn_date = datetime.now(UTC).astimezone().strftime("%d-%m-%Y")
            token = self._generate_initiate_token(content.order_id, content.amount, txn_date)

            success_url = self._config.success_url or content.success_url
            failure_url = self._config.failure_url or content.failure_url

            form_fields = {
                "MERCHANTID": self._config.merchant_id,
                "APPID": self._config.app_id,
                "APPNAME": self._config.app_name,
                "TXNID": content.order_id,
                "TXNDATE": txn_date,
                "TXNCRNCY": "NPR",
                "TXNAMT": str(content.amount),
                "REFERENCEID": content.order_id,
                "REMARKS": content.description or "",
                "PARTICULARS": content.description or "",
                "TOKEN": token,
                "SUCCESSURL": success_url or "",
                "FAILUREURL": failure_url or "",
            }

            result = PaymentResult(
                data=FormResponse(target_url=self._login_url, form_fields=form_fields),
                success=True,
                message="ConnectIPS payment form generated successfully",
            )
            return convert_to(result_cls, result)

        return self._run_result(result_cls, _call)

    def verify_payment(self, result_cls: type[T], content: str) -> T:
        """Check a ConnectIPS payment against the callback data it sent us.

        Args:
            result_cls: The shape the result should be turned into.
            content: The callback params, as a JSON string or a dict, e.g.
                ``{"TXNID": "...", "STATUS": "...", "expectedAmount": 100}``.

        Returns:
            A ``result_cls`` wrapping the verification result.

        """
        if not content:
            raise ValidationError("Verification content cannot be null or empty")

        def _call() -> T:
            callback = json.loads(content) if isinstance(content, str) else content
            txn_id = callback.get("TXNID") or callback.get("transaction_id") or callback.get("reference_id")
            if not txn_id:
                return convert_to(result_cls, PaymentResult(success=False, message="TXNID not found in callback"))

            callback_status = str(callback.get("STATUS") or callback.get("status") or "").upper()
            if callback_status in ("FAILED", "CANCELLED"):
                result = PaymentResult(
                    data=VerificationResponse(status=normalize_status(callback_status)),
                    success=False,
                    message="Payment was not completed",
                )
                return convert_to(result_cls, result)

            return self._validate_transaction(result_cls, txn_id, callback.get("expectedAmount"))

        return self._run_result(result_cls, _call)

    def _validate_transaction(self, result_cls: type[T], txn_id: str, expected_amount) -> T:
        token = self._generate_validation_token(txn_id, expected_amount)
        request = VerificationRequest(
            merchant_id=self._config.merchant_id,
            app_id=self._config.app_id,
            reference_id=txn_id,
            txn_amount=expected_amount,
            token=token,
        )
        auth = base64.b64encode(f"{self._config.app_id}:{self._config.app_password}".encode()).decode()
        response = self._api_service.get_async_result(
            VerificationResponse,
            self._validation_url,
            ApiEndpoints.CONNECTIPS.VALIDATION_METHOD,
            header_param={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
            request_body=request,
        )
        if response.status == STATUS_NOT_FOUND:
            raise ProviderError("Payment not found")
        if response.status == STATUS_INVALID_TOKEN or response.token_valid is False:
            raise ProviderError("Invalid token")
        if expected_amount is not None:
            actual = int(response.txn_amount) if response.txn_amount is not None else None
            if actual is None or int(expected_amount) != actual:
                raise ProviderError(f"Expected amount {expected_amount}, got {response.txn_amount}")
        success = response.status == STATUS_SUCCESS
        response.status = normalize_status(response.status) if response.status else None
        result = PaymentResult(
            data=response,
            success=success,
            message=response.status_desc or "",
        )
        return convert_to(result_cls, result)

    def _validate_initiate(self, request: PaymentRequest) -> None:
        if not request.amount or request.amount <= 0:
            raise ValidationError("amount must be positive")
        if not request.order_id:
            raise ValidationError("order_id is required")
        if not request.success_url and not self._config.success_url:
            raise ValidationError("success_url is required")

    def _generate_initiate_token(self, txn_id: str, amount: int, txn_date: str) -> str:
        message = f"{self._config.merchant_id},{self._config.app_id},{txn_id},{amount},{txn_date}"
        return generate_rsa_signature(message, self._private_key)

    def _generate_validation_token(self, txn_id: str, amount: int) -> str:
        message = f"{self._config.merchant_id},{self._config.app_id},{txn_id},{amount}"
        return generate_rsa_signature(message, self._private_key)

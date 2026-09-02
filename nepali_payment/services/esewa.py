"""eSewa payment service."""

import json
from typing import Any, TypeVar

from nepali_payment.constants import ApiEndpoints
from nepali_payment.enums import PaymentAction, PaymentMethod, PaymentMode
from nepali_payment.exceptions import PaymentError
from nepali_payment.factory import _endpoint_for
from nepali_payment.helpers import (
    convert_to,
    decode_base64_content,
    generate_hmac_sha256_signature,
)
from nepali_payment.http import ApiService
from nepali_payment.models import PaymentResult
from nepali_payment.models.esewa import PaymentRequest, PaymentResponse, RequestResponse
from nepali_payment.services.base import BasePaymentService

T = TypeVar("T")


class PaymentService(BasePaymentService):
    """eSewa integration.

    To start a payment we sign the request with a secret key (HMAC-SHA256) and
    send it to eSewa. To check a payment we decode a base64 payload. eSewa is
    different from the other gateways: when something fails, it raises a
    ``PaymentError`` instead of returning a failed result.
    """

    _api = ApiEndpoints.ESEWA

    def __init__(self, secret_key: str, payment_mode: PaymentMode, api: ApiService | None = None):
        """Create an eSewa service.

        Args:
            secret_key: The eSewa secret key, used to sign our requests.
            payment_mode: ``SANDBOX`` or ``PRODUCTION``.
            api: Your own HTTP client (optional). If left out, a new one is made.

        """
        if not secret_key:
            raise ValueError("Secret key cannot be null or empty.")
        self._secret_key = secret_key
        super().__init__(payment_mode, api)

    def _endpoint(self, action: PaymentAction):
        """Return (full endpoint, method) for an eSewa operation."""
        return _endpoint_for(PaymentMethod.ESEWA, action, self._payment_mode)

    def initiate_payment(self, result_cls: type[T], content: Any) -> T:
        """Start an eSewa payment.

        Args:
            result_cls: The shape the result should be turned into.
            content: An :class:`~nepali_payment.models.esewa.PaymentRequest`.

        Returns:
            A ``result_cls`` holding eSewa's response.

        """
        if not isinstance(content, PaymentRequest):
            raise TypeError("Content must be of type PaymentRequest")

        try:
            signature = self._generate_signature(content)
            content.signature = signature
            endpoint, method = self._endpoint(PaymentAction.PROCESS_PAYMENT)
            key_value_pairs = content.to_dict()

            response = self._api_service.get_async_result(
                str,
                endpoint,
                method,
                key_value_pairs=key_value_pairs,
            )
            result = PaymentResult(
                data=RequestResponse(payment_url=response or ""),
                success=True,
                message="Payment initiated successfully",
            )
            return convert_to(result_cls, result)
        except PaymentError:
            raise
        except Exception as exc:
            raise PaymentError(f"Failed to initiate eSewa payment: {exc}") from exc

    def verify_payment(self, result_cls: type[T], content: str) -> T:
        """Check an eSewa payment by decoding its response payload.

        Args:
            result_cls: The shape the result should be turned into.
            content: The base64-encoded response eSewa gives us.

        Returns:
            A ``result_cls`` holding the decoded response.

        """
        if not content:
            raise ValueError("Verification content cannot be null or empty")
        try:
            decoded = decode_base64_content(content)
            data = json.loads(decoded)
            transaction_data = PaymentResponse(**data)
            # eSewa marks a completed payment with status "COMPLETE"; any other
            # status (CANCELLED, FAILED, etc.) is not a success.
            status = str(transaction_data.status or "").upper()
            verified = status == "COMPLETE"
            result = PaymentResult(
                data=transaction_data,
                success=verified,
                message="Payment verified successfully" if verified else f"Payment status: {status or 'unknown'}",
            )
            return convert_to(result_cls, result)
        except PaymentError:
            raise
        except Exception as exc:
            raise PaymentError(f"Failed to verify eSewa payment: {exc}") from exc

    def _generate_signature(self, request: PaymentRequest) -> str:
        signed_fields = [f.strip() for f in (request.signed_field_names or "").split(",") if f.strip()]
        parts = []
        for field in signed_fields:
            value = getattr(request, field, None)
            if value is not None:
                parts.append(f"{field}={value}")
        message = ",".join(parts)
        return generate_hmac_sha256_signature(message, self._secret_key)

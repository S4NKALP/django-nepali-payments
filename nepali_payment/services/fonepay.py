"""Fonepay payment service QR generation, status, tax refund."""

import json
from typing import Any, TypeVar

from nepali_payment.constants import ApiEndpoints
from nepali_payment.enums import PaymentMode
from nepali_payment.exceptions import ValidationError
from nepali_payment.helpers import convert_to, generate_hmac_sha512
from nepali_payment.http import ApiService
from nepali_payment.models import PaymentResult
from nepali_payment.models.fonepay import (
    QrRequest,
    QrResponse,
    QrStatusRequest,
    QrStatusResponse,
    StaticQrRequest,
    StaticQrResponse,
    TaxRefundRequest,
    TaxRefundResponse,
)
from nepali_payment.services.base import BasePaymentService

T = TypeVar("T")


class PaymentService(BasePaymentService):
    """Fonepay QR integration.

    Handles QR generation, checking the payment status, and tax refunds. Every
    request is signed with a secret key (HMAC-SHA512) and sent to Fonepay as
    JSON. Errors are turned into a failed ``PaymentResult``.
    """

    _api = ApiEndpoints.FONEPAY

    def __init__(self, secret_key: str, payment_mode: PaymentMode, api: ApiService | None = None):
        """Create a Fonepay service.

        Args:
            secret_key: Fonepay's secret key.
            payment_mode: ``SANDBOX`` or ``PRODUCTION``.
            api: Your own HTTP client (optional). If left out, a new one is made.

        """
        if not secret_key:
            raise ValueError("Secret key cannot be null or empty.")
        self._secret_key = secret_key
        super().__init__(payment_mode, api)

    def initiate_payment(self, result_cls: type[T], content: Any) -> T:
        """Generate a Fonepay payment QR code.

        Args:
            result_cls: The shape the result should be turned into.
            content: A :class:`~nepali_payment.models.fonepay.QrRequest`.

        Returns:
            A ``result_cls`` wrapping the payment result, including the QR data.

        Raises:
            TypeError: If ``content`` is not a QrRequest.

        """
        if not isinstance(content, QrRequest):
            raise TypeError("Content must be of type QrRequest")

        def _call() -> T:
            content.data_validation = self._generate_qr_signature(content)
            endpoint = f"{self.base_url}{ApiEndpoints.FONEPAY.QR_GENERATE_URL}"
            headers = {"Content-Type": "application/json"}
            response = self._api_service.get_async_result(
                QrResponse,
                endpoint,
                ApiEndpoints.FONEPAY.QR_GENERATE_METHOD,
                header_param=headers,
                request_body=content,
            )
            result = PaymentResult(
                data=response,
                success=bool(response.success),
                message=response.message or "",
            )
            return convert_to(result_cls, result)

        return self._run_result(result_cls, _call)

    def verify_payment(self, result_cls: type[T], content: str) -> T:
        """Check whether a Fonepay payment has settled, using its PRN.

        Args:
            result_cls: The shape the result should be turned into.
            content: A JSON string with ``prn``, ``merchantCode``, ``username``
                and ``password``.

        Returns:
            A ``result_cls`` wrapping the payment result, including the status.

        """
        if not content:
            raise ValidationError("Verification content cannot be null or empty")

        def _call() -> T:
            verification_data = json.loads(content)
            prn = verification_data["prn"]
            merchant_code = verification_data["merchantCode"]
            status_request = QrStatusRequest(
                prn=prn,
                merchant_code=merchant_code,
                data_validation=self._generate_qr_status_signature(prn, merchant_code),
                username=verification_data["username"],
                password=verification_data["password"],
            )
            endpoint = f"{self.base_url}{ApiEndpoints.FONEPAY.QR_STATUS_URL}"
            headers = {"Content-Type": "application/json"}
            response = self._api_service.get_async_result(
                QrStatusResponse,
                endpoint,
                ApiEndpoints.FONEPAY.QR_STATUS_METHOD,
                header_param=headers,
                request_body=status_request,
            )
            result = PaymentResult(data=response, success=True, message="QR status checked successfully")
            return convert_to(result_cls, result)

        return self._run_result(result_cls, _call)

    def process_static_qr(self, result_cls: type[T], request: StaticQrRequest) -> T:
        """Fetch the fixed Fonepay static QR for a merchant.

        A static QR is one reusable QR (the customer types in the amount when
        scanning). ``data_validation`` is worked out from ``prn`` and the
        ``merchant_code``.

        Args:
            result_cls: The shape the result should be turned into.
            request: A :class:`~nepali_payment.models.fonepay.StaticQrRequest`.

        Returns:
            A ``result_cls`` wrapping the payment result, including the QR string.

        """
        if not isinstance(request, StaticQrRequest):
            raise TypeError("Content must be of type StaticQrRequest")

        def _call() -> T:
            request.data_validation = self._generate_qr_status_signature(request.prn, request.merchant_code)
            endpoint = f"{self.base_url}{ApiEndpoints.FONEPAY.STATIC_QR_URL}"
            headers = {"Content-Type": "application/json"}
            response = self._api_service.get_async_result(
                StaticQrResponse,
                endpoint,
                ApiEndpoints.FONEPAY.STATIC_QR_METHOD,
                header_param=headers,
                request_body=request,
            )
            result = PaymentResult(
                data=response,
                success=True,
                message="Static QR retrieved successfully",
            )
            return convert_to(result_cls, result)

        return self._run_result(result_cls, _call)

    def process_tax_refund(self, result_cls: type[T], request: TaxRefundRequest) -> T:
        """Process a Fonepay tax refund.

        Args:
            result_cls: The shape the result should be turned into.
            request: A :class:`~nepali_payment.models.fonepay.TaxRefundRequest`.

        Returns:
            A ``result_cls`` wrapping the payment result.

        """

        def _call() -> T:
            request.data_validation = self._generate_tax_refund_signature(request)
            endpoint = f"{self.base_url}{ApiEndpoints.FONEPAY.TAX_REFUND_URL}"
            headers = {"Content-Type": "application/json"}
            response = self._api_service.get_async_result(
                TaxRefundResponse,
                endpoint,
                ApiEndpoints.FONEPAY.TAX_REFUND_METHOD,
                header_param=headers,
                request_body=request,
            )
            result = PaymentResult(
                data=response,
                success=bool(response.success),
                message=response.message or "",
            )
            return convert_to(result_cls, result)

        return self._run_result(result_cls, _call)

    def _generate_qr_signature(self, request: QrRequest) -> str:
        base_fields = (request.amount, request.prn, request.merchant_code, request.remarks1, request.remarks2)
        if any(v is None for v in base_fields):
            raise ValidationError("QrRequest is missing required signature fields")
        if request.tax_refund is None:
            message = f"{request.amount},{request.prn},{request.merchant_code},{request.remarks1},{request.remarks2}"
        else:
            if request.tax_amount is None:
                raise ValidationError("QrRequest tax_amount is required when tax_refund is set")
            message = (
                f"{request.amount},{request.prn},{request.merchant_code},"
                f"{request.remarks1},{request.remarks2},"
                f"{request.tax_amount},{request.tax_refund}"
            )
        return generate_hmac_sha512(message, self._secret_key)

    def _generate_qr_status_signature(self, prn: str, merchant_code: str) -> str:
        message = f"{prn},{merchant_code}"
        return generate_hmac_sha512(message, self._secret_key)

    def _generate_tax_refund_signature(self, request: TaxRefundRequest) -> str:
        message = (
            f"{request.fonepay_trace_id},{request.merchant_prn},"
            f"{request.invoice_number},{request.invoice_date},"
            f"{request.transaction_amount},{request.merchant_code}"
        )
        return generate_hmac_sha512(message, self._secret_key)

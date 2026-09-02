"""
Accept payments in Nepal with a consistent API.

Supports Khalti, eSewa, Fonepay (dynamic QR, static QR, status polling, tax
refund) and ConnectIPS. Every gateway uses the same ``PaymentManager`` and
returns a ``PaymentResult``. Real-time Fonepay status uses HTTP polling instead
of a persistent WebSocket so it works on shared hosting.

"""

from nepali_payment.enums import PaymentAction, PaymentMethod, PaymentMode
from nepali_payment.exceptions import (
    AuthenticationError,
    NetworkError,
    PaymentError,
    ProviderError,
    TimeoutError,
    UnsupportedGatewayError,
    ValidationError,
)
from nepali_payment.helpers import (
    decode_base64_content,
    generate_hmac_sha256,
    generate_hmac_sha256_signature,
    generate_hmac_sha512,
)
from nepali_payment.manager import PaymentManager
from nepali_payment.models import PaymentResult
from nepali_payment.monitor import (
    FonepayPaymentMonitor,
    PaymentCancelledEventArgs,
    PaymentCredentials,
    PaymentErrorEventArgs,
    PaymentStatusEventArgs,
    PaymentTimeoutEventArgs,
    PaymentVerifiedEventArgs,
)
from nepali_payment.service_factory import get_payment_service
from nepali_payment.services.base import BasePaymentService

try:  # prefer the installed package's version so it cannot drift from pyproject
    from importlib import metadata as _metadata

    __version__ = _metadata.version("django-nepali-payment")
except _metadata.PackageNotFoundError:  # pragma: no cover - source-tree fallback
    __version__ = "1.0.0"

__all__ = [
    "AuthenticationError",
    "BasePaymentService",
    "FonepayPaymentMonitor",
    "NetworkError",
    "PaymentAction",
    "PaymentCancelledEventArgs",
    "PaymentCredentials",
    "PaymentError",
    "PaymentErrorEventArgs",
    "PaymentManager",
    "PaymentMethod",
    "PaymentMode",
    "PaymentResult",
    "PaymentStatusEventArgs",
    "PaymentTimeoutEventArgs",
    "PaymentVerifiedEventArgs",
    "ProviderError",
    "TimeoutError",
    "UnsupportedGatewayError",
    "ValidationError",
    "decode_base64_content",
    "generate_hmac_sha256",
    "generate_hmac_sha256_signature",
    "generate_hmac_sha512",
    "get_payment_service",
]

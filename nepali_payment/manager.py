from typing import Any, TypeVar

from nepali_payment.enums import PaymentMethod, PaymentMode
from nepali_payment.exceptions import ValidationError
from nepali_payment.http import ApiService
from nepali_payment.service_factory import get_payment_service

T = TypeVar("T")


class PaymentManager:
    """The easy entry point for taking payments.

    Pick a gateway (Khalti, eSewa, Fonepay, ConnectIPS), a mode (sandbox or
    production) and your secret key once. Then you can start a payment, check a
    payment, or refund tax without worrying about which provider you chose.
    """

    def __init__(
        self,
        payment_method: PaymentMethod,
        payment_mode: PaymentMode,
        secret_key: str,
        api=None,
        config=None,
    ):
        """Create a manager for one gateway and one mode.

        Args:
            payment_method: The gateway to use (eSewa, Khalti, Fonepay,
                ConnectIPS).
            payment_mode: ``SANDBOX`` or ``PRODUCTION``.
            secret_key: The provider's secret key, for signing / authentication.
                Not used for ConnectIPS - that gateway uses ``config`` instead.
            api: Your own HTTP client (optional). If left out, a new one is made.
            config: For ConnectIPS only: a :class:`ConnectIpsConfig` holding the
                merchant credentials and certificate.

        """
        if not secret_key and payment_method != PaymentMethod.CONNECTIPS:
            raise ValueError("Secret key cannot be null or empty.")
        self._secret_key = secret_key
        self._method = payment_method
        self._mode = payment_mode
        self._api = api
        self._config = config
        self._service_cache = None

    def _api_service(self):
        """Return the shared HTTP client, creating it on the first call.

        We reuse the same :class:`~nepali_payment.http.ApiService` (and its
        pooled connection) for every operation. That way, when this manager runs
        lots of calls in a loop, it never opens a fresh connection each time
        (the "N+1 connections" problem).
        """
        if self._api is None:
            self._api = ApiService()
        return self._api

    def _service(self):
        """Build the service for our gateway, sharing the HTTP client.

        The service is built once and reused. That is both faster (e.g. for
        ConnectIPS it avoids re-parsing the RSA certificate on every call) and
        keeps a stable HTTP client across operations.
        """
        if self._service_cache is None:
            self._service_cache = get_payment_service(
                self._method, self._secret_key, self._mode, api=self._api_service(), config=self._config
            )
        return self._service_cache

    def initiate_payment(self, result_cls: type[T], content: Any) -> T:
        """Start a payment and return a typed result.

        Args:
            result_cls: The shape the result should be turned into, e.g.
                :class:`~nepali_payment.models.PaymentResult`.
            content: The request model for your gateway.

        Returns:
            A ``result_cls`` wrapping the provider's response.

        Raises:
            ValidationError: If ``content`` is ``None``.

        """
        if content is None:
            raise ValidationError("Payment content cannot be null.")
        service = self._service()
        return service.initiate_payment(result_cls, content)

    def verify_payment(self, result_cls: type[T], content: str) -> T:
        """Check whether a previously started payment went through.

        Args:
            result_cls: The shape the result should be turned into.
            content: The provider's reference (e.g. Khalti ``pidx``, Fonepay PRN).

        Returns:
            A ``result_cls`` instance wrapping the verification response.

        Raises:
            ValidationError: If ``content`` is empty.

        """
        if not content:
            raise ValidationError("Verification content cannot be null or empty.")
        service = self._service()
        return service.verify_payment(result_cls, content)

    def process_tax_refund(self, result_cls: type[T], request: Any) -> T:
        """Process a Fonepay tax refund (only available for Fonepay).

        Args:
            result_cls: The shape the result should be turned into.
            request: A :class:`~nepali_payment.models.fonepay.TaxRefundRequest`.

        Returns:
            A ``result_cls`` wrapping the refund response.

        Raises:
            ValidationError: If the gateway is not Fonepay.

        """
        service = self._service()
        if hasattr(service, "process_tax_refund"):
            return service.process_tax_refund(result_cls, request)
        raise ValidationError("Tax refund is only supported for Fonepay.")

    def process_static_qr(self, result_cls: type[T], request: Any) -> T:
        """Fetch the fixed Fonepay static QR (Fonepay only).

        A static QR is one reusable merchant QR - the customer types in the
        amount when scanning - unlike the per-transaction dynamic QR.

        Args:
            result_cls: The shape the result should be turned into.
            request: A :class:`~nepali_payment.models.fonepay.StaticQrRequest`.

        Returns:
            A ``result_cls`` wrapping the static QR response.

        Raises:
            ValidationError: If the gateway is not Fonepay.

        """
        service = self._service()
        if hasattr(service, "process_static_qr"):
            return service.process_static_qr(result_cls, request)
        raise ValidationError("Static QR is only supported for Fonepay.")

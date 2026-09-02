from nepali_payment.enums import PaymentMethod, PaymentMode
from nepali_payment.exceptions import UnsupportedGatewayError
from nepali_payment.services import connectips, esewa, fonepay, khalti

# Standard gateways: secret_key-driven services keyed by gateway.
_SERVICES: dict[PaymentMethod, type] = {
    PaymentMethod.ESEWA: esewa.PaymentService,
    PaymentMethod.KHALTI: khalti.PaymentService,
    PaymentMethod.FONEPAY: fonepay.PaymentService,
}


def get_payment_service(
    payment_method: PaymentMethod,
    secret_key: str,
    payment_mode: PaymentMode,
    api=None,
    config=None,
):
    """Pick the right payment service for the gateway you chose.

    ConnectIPS does not use a secret key - it needs a full config object
    (merchant id, app credentials, certificate) instead.

    Args:
        payment_method: Which gateway to use.
        secret_key: The provider's secret key, for signing / authentication.
        payment_mode: ``SANDBOX`` or ``PRODUCTION``.
        api: Your own HTTP client (optional). If left out, a new one is made.
        config: The ConnectIPS :class:`ConnectIpsConfig` (required for ConnectIPS).

    Returns:
        A ready-to-use payment service for the chosen gateway.

    Raises:
        ValueError: If ``secret_key`` is empty (for non-ConnectIPS gateways).
        UnsupportedGatewayError: If the gateway is not supported.

    """
    if payment_method == PaymentMethod.CONNECTIPS:
        return connectips.PaymentService(config, payment_mode, api=api)

    service_cls = _SERVICES.get(payment_method)
    if service_cls is None:
        raise UnsupportedGatewayError(f"The combination of {payment_method} and {payment_mode} is not supported.")

    if not secret_key:
        raise ValueError("Secret key cannot be null or empty.")
    return service_cls(secret_key, payment_mode, api=api)

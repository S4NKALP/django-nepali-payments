"""Service interface + endpoint resolution factories."""

from functools import lru_cache

from nepali_payment.constants import ApiEndpoints
from nepali_payment.enums import PaymentAction, PaymentMethod, PaymentMode
from nepali_payment.exceptions import UnsupportedGatewayError

# Each entry: (config_class, action -> (url_attr, method_attr))
_ENDPOINTS: dict[
    PaymentMethod,
    tuple[type, dict[PaymentAction, tuple[str, str]]],
] = {
    PaymentMethod.ESEWA: (
        ApiEndpoints.ESEWA,
        {
            PaymentAction.PROCESS_PAYMENT: ("PROCESS_PAYMENT_URL", "PROCESS_PAYMENT_METHOD"),
            PaymentAction.VERIFY_PAYMENT: ("VERIFY_PAYMENT_URL", "VERIFY_PAYMENT_METHOD"),
        },
    ),
    PaymentMethod.KHALTI: (
        ApiEndpoints.KHALTI,
        {
            PaymentAction.PROCESS_PAYMENT: ("PROCESS_PAYMENT_URL", "PROCESS_PAYMENT_METHOD"),
            PaymentAction.VERIFY_PAYMENT: ("VERIFY_PAYMENT_URL", "VERIFY_PAYMENT_METHOD"),
        },
    ),
    PaymentMethod.FONEPAY: (
        ApiEndpoints.FONEPAY,
        {
            PaymentAction.PROCESS_PAYMENT: ("QR_GENERATE_URL", "QR_GENERATE_METHOD"),
            PaymentAction.VERIFY_PAYMENT: ("QR_STATUS_URL", "QR_STATUS_METHOD"),
        },
    ),
}


@lru_cache(maxsize=32)
def _endpoint_for(
    gateway: PaymentMethod,
    action: PaymentAction,
    mode: PaymentMode,
) -> tuple[str, str]:
    """
    Get the API address and HTTP method for a gateway operation.

    Args:
        gateway: The payment method.
        action: The operation (initiate or verify).
        mode: Sandbox or production.

    Returns:
        A ``(url, http_method)`` tuple where ``http_method`` is ``"POST"`` or
        ``"GET"``.

    Raises:
        UnsupportedGatewayError: For unsupported gateway/action combinations.

    """
    entry = _ENDPOINTS.get(gateway)
    if entry is None:
        raise UnsupportedGatewayError(f"The combination of {gateway}, {mode}, and {action} is not supported.")

    config, action_map = entry
    attrs = action_map.get(action)
    if attrs is None:
        raise UnsupportedGatewayError(f"The combination of {gateway}, {mode}, and {action} is not supported.")

    base = config.BASE_URL if mode == PaymentMode.PRODUCTION else config.SANDBOX_BASE_URL
    url_attr, method_attr = attrs
    return base + getattr(config, url_attr), getattr(config, method_attr)

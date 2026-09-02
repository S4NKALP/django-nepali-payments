class PaymentError(Exception):
    """Base class for all payment errors.

    Attributes:
        category: Machine-readable error category used for unified handling.
        provider_message: Raw message from the provider, when available.

    """

    category = "PAYMENT_ERROR"

    def __init__(self, message: str, provider_message: str | None = None):
        """Create a payment error.

        Args:
            message: Human-readable error description.
            provider_message: Optional raw provider-supplied message.

        """
        super().__init__(message)
        self.provider_message = provider_message


class ValidationError(PaymentError):
    """Request data failed validation before reaching the provider."""

    category = "VALIDATION_ERROR"


class AuthenticationError(PaymentError):
    """The provider rejected the supplied credentials/secret."""

    category = "AUTHENTICATION_ERROR"


class NetworkError(PaymentError):
    """A transport-level failure occurred while reaching the provider."""

    category = "NETWORK_ERROR"


class ProviderError(PaymentError):
    """The provider returned a non-success HTTP response."""

    category = "PROVIDER_ERROR"


class TimeoutError(PaymentError):
    """A request exceeded the configured timeout.

    Note: this class shadows Python's builtin :exc:`TimeoutError`. It is kept
    as a public name for backwards compatibility, but nothing inside this
    package catches the bare name, so the builtin is never shadowed in our own
    code. Import it explicitly (``from nepali_payment import TimeoutError``) to
    avoid confusion.
    """

    category = "TIMEOUT_ERROR"


class UnsupportedGatewayError(PaymentError):
    """Raised for unsupported gateway/version combinations."""

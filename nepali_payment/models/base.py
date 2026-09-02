from dataclasses import dataclass
from typing import Any

from nepali_payment.exceptions import PaymentError


@dataclass
class BaseResponse:
    """The common fields every response carries.

    Each gateway response keeps its own specific fields, but they all share
    these basics: a status, a message, some data, and whether it worked.
    """

    status: int = 200
    message: str = ""
    data: Any | None = None
    success: bool = True
    error_code: int | None = None


@dataclass
class PaymentResult(BaseResponse):
    """The standard answer every service returns.

    Holds whether the payment worked (``success``), a message, and the raw data
    from the provider (``data``). It can be used like a ``bool`` (true = worked)
    and can raise an error for you if it failed.
    """

    def __bool__(self) -> bool:
        """Return True when the payment operation succeeded."""
        return bool(self.success)

    def raise_for_status(self) -> "PaymentResult":
        """Raise an error if the payment failed, otherwise return ``self``.

        Handy after a call: this throws a :class:`PaymentError` when
        ``success`` is False, so you can stop and handle the problem.

        Raises:
            PaymentError: When ``success`` is False.

        """
        if not self.success:
            raise PaymentError(self.message or "Payment failed")
        return self

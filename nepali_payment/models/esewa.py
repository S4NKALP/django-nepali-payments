from dataclasses import asdict, dataclass


@dataclass(slots=True)
class PaymentRequest:
    """eSewa payment initiation request"""

    amount: str | None = None
    tax_amount: str | None = None
    total_amount: str | None = None
    transaction_uuid: str | None = None
    product_code: str | None = None
    product_service_charge: str | None = None
    product_delivery_charge: str | None = None
    success_url: str | None = None
    failure_url: str | None = None
    signed_field_names: str | None = None
    signature: str | None = None

    def to_dict(self) -> dict:
        """Serialize this request to a plain dict for form encoding."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PaymentResponse:
    """eSewa verification response"""

    status: str | None = None
    signature: str | None = None
    transaction_code: str | None = None
    total_amount: float | None = None
    transaction_uuid: str | None = None
    product_code: str | None = None
    signed_field_names: str | None = None


@dataclass
class RequestResponse:
    """eSewa initiation response wrapper"""

    payment_url: str | None = None

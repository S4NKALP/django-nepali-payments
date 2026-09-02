from dataclasses import dataclass


@dataclass(slots=True)
class CustomerInfo:
    """Khalti customer info"""

    name: str | None = None
    email: str | None = None
    phone: str | None = None


@dataclass(slots=True)
class ProductDetail:
    """Khalti product detail"""

    identity: str | None = None
    name: str | None = None
    total_price: int | None = None
    quantity: int | None = None
    unit_price: int | None = None


@dataclass(slots=True)
class AmountBreakdown:
    """Khalti amount breakdown"""

    label: str | None = None
    amount: int | None = None


@dataclass(slots=True)
class PaymentRequest:
    """Khalti payment initiation request"""

    return_url: str | None = None
    website_url: str | None = None
    amount: int | None = None
    purchase_order_id: str | None = None
    purchase_order_name: str | None = None
    customer_info: CustomerInfo | None = None
    product_details: list[ProductDetail] | None = None
    amount_breakdown: list[AmountBreakdown] | None = None


@dataclass
class RequestResponse:
    """Khalti initiation response"""

    pidx: str | None = None
    payment_url: str | None = None
    expires_at: str | None = None
    expires_in: int | None = None


@dataclass
class PaymentResponse:
    """Khalti verification response"""

    pidx: str | None = None
    total_amount: float | None = None
    status: str | None = None
    transaction_id: str | None = None
    fee: float | None = None
    refunded: bool | None = None

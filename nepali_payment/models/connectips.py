from dataclasses import dataclass, field


@dataclass(slots=True)
class PaymentRequest:
    """ConnectIPS payment initiation request (form POST to the login page)."""

    order_id: str | None = None
    amount: int | None = None
    description: str | None = None
    success_url: str | None = None
    failure_url: str | None = None


@dataclass
class FormResponse:
    """ConnectIPS initiation response — form fields to POST to the gateway."""

    target_url: str | None = None
    form_fields: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class VerificationRequest:
    """ConnectIPS validation request sent to the validate-response API."""

    merchant_id: str | None = None
    app_id: str | None = None
    reference_id: str | None = None
    txn_amount: int | None = None
    token: str | None = None

    def to_dict(self) -> dict:
        """Serialize to the PascalCase JSON body ConnectIPS validates."""
        return {
            "MerchantID": self.merchant_id,
            "AppID": self.app_id,
            "ReferenceID": self.reference_id,
            "TxnAmount": self.txn_amount,
            "Token": self.token,
        }


@dataclass
class VerificationResponse:
    """ConnectIPS validation API response."""

    status: str | None = None
    status_desc: str | None = None
    trans_ref_id: str | None = None
    reference_id: str | None = None
    txn_amount: int | None = None
    txn_date: str | None = None
    token_valid: bool | None = None

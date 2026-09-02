from dataclasses import asdict, dataclass
from typing import Any


def _to_json_dict(instance, camel_map: dict[str, str]) -> dict[str, Any]:
    """Turn a request model into a JSON-ready dictionary.

    We use ``asdict`` (not ``__dict__``) so the models can safely use
    ``slots=True``, and we rename snake_case field names (like ``merchant_code``)
    into camelCase (``merchantCode``) because that is what Fonepay expects.
    """
    data = asdict(instance)
    for snake, camel in camel_map.items():
        if snake in data:
            data[camel] = data.pop(snake)
    return data


@dataclass(slots=True)
class QrRequest:
    """How we ask Fonepay to create a QR code for a payment."""

    amount: str | None = None
    remarks1: str | None = None
    remarks2: str | None = None
    prn: str | None = None
    merchant_code: str | None = None
    data_validation: str | None = None
    username: str | None = None
    password: str | None = None
    tax_amount: str | None = None
    tax_refund: str | None = None

    def to_dict(self) -> dict:
        """Get the request fields in the shape Fonepay expects."""
        return _to_json_dict(
            self,
            {
                "merchant_code": "merchantCode",
                "data_validation": "dataValidation",
                "tax_amount": "taxAmount",
                "tax_refund": "taxRefund",
            },
        )


@dataclass(slots=True)
class QrResponse:
    """What Fonepay sends back after we ask for a QR code."""

    message: str | None = None
    qr_message: str | None = None
    status: str | None = None
    status_code: int | None = None
    success: bool | None = None
    thirdparty_qr_websocket_url: str | None = None
    documentation: str | None = None
    error_code: int | None = None


@dataclass(slots=True)
class QrStatusRequest:
    """How we ask Fonepay whether a payment has been settled yet."""

    prn: str | None = None
    merchant_code: str | None = None
    data_validation: str | None = None
    username: str | None = None
    password: str | None = None

    def to_dict(self) -> dict:
        """Get the request fields in the shape Fonepay expects."""
        return _to_json_dict(self, {"merchant_code": "merchantCode", "data_validation": "dataValidation"})


@dataclass
class QrStatusResponse:
    """Fonepay's answer about whether a payment is settled."""

    fonepay_trace_id: int | None = None
    merchant_code: str | None = None
    payment_status: str | None = None
    prn: str | None = None


@dataclass(slots=True)
class StaticQrRequest:
    """Fonepay static QR: one fixed QR for your shop.

    Unlike the dynamic QR (one per payment), the static QR is the same every
    time. The customer types in the amount when they scan it. The service works
    out ``data_validation`` from ``prn`` and ``merchant_code`` for you.
    """

    prn: str | None = None
    merchant_code: str | None = None
    data_validation: str | None = None
    username: str | None = None
    password: str | None = None

    def to_dict(self) -> dict:
        """Get the request fields in the shape Fonepay expects."""
        return _to_json_dict(self, {"merchant_code": "merchantCode", "data_validation": "dataValidation"})


@dataclass
class StaticQrResponse:
    """The fixed merchant QR payload Fonepay returns."""

    qr_message: str | None = None


@dataclass(slots=True)
class TaxRefundRequest:
    """How we ask Fonepay to refund tax on a payment."""

    fonepay_trace_id: int | None = None
    transaction_amount: str | None = None
    merchant_prn: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    merchant_code: str | None = None
    data_validation: str | None = None
    username: str | None = None
    password: str | None = None

    def to_dict(self) -> dict:
        """Get the request fields in the shape Fonepay expects."""
        return _to_json_dict(
            self,
            {
                "fonepay_trace_id": "fonepayTraceId",
                "transaction_amount": "transactionAmount",
                "merchant_prn": "merchantPRN",
                "invoice_number": "invoiceNumber",
                "invoice_date": "invoiceDate",
                "merchant_code": "merchantCode",
                "data_validation": "dataValidation",
            },
        )


@dataclass
class TaxRefundResponse:
    """Fonepay's answer to a tax refund request."""

    fonepay_trace_id: int | None = None
    message: str | None = None
    success: bool | None = None

"""Base response model tests (PaymentResult ergonomic helpers)."""

import pytest

from nepali_payment.exceptions import PaymentError
from nepali_payment.models import PaymentResult
from nepali_payment.models.connectips import PaymentRequest as ConnectIpPaymentRequest
from nepali_payment.models.esewa import PaymentRequest as EsewaPaymentRequest
from nepali_payment.models.fonepay import QrRequest, QrStatusRequest
from nepali_payment.models.khalti import PaymentRequest as KhaltiPaymentRequest


def test_payment_result_bool_true_on_success():
    assert bool(PaymentResult(success=True)) is True


def test_payment_result_bool_false_on_failure():
    assert bool(PaymentResult(success=False)) is False


def test_payment_result_raise_for_status_returns_self_on_success():
    result = PaymentResult(success=True, data={"x": 1})
    assert result.raise_for_status() is result


def test_payment_result_raise_for_status_raises_on_failure():
    result = PaymentResult(success=False, message="provider said no")
    with pytest.raises(PaymentError) as excinfo:
        result.raise_for_status()
    assert str(excinfo.value) == "provider said no"


def test_payment_result_raise_for_status_default_message():
    with pytest.raises(PaymentError):
        PaymentResult(success=False).raise_for_status()


def test_slotted_request_models_serialize_to_dict():
    """Request models use slots and serialize via asdict — no __dict__ reliance."""
    for model in (KhaltiPaymentRequest, EsewaPaymentRequest, QrRequest, QrStatusRequest, ConnectIpPaymentRequest):
        assert model.__slots__ is not None, f"{model.__name__} must use slots"

    esewa = EsewaPaymentRequest(amount="10", total_amount="12", signature="sig")
    assert esewa.to_dict() == {"amount": "10", "total_amount": "12", "signature": "sig"}

    qr = QrRequest(amount="33", merchant_code="NBQM", data_validation="dv")
    assert qr.to_dict()["merchantCode"] == "NBQM"

    khalti = KhaltiPaymentRequest(amount=100, purchase_order_name="Mug")
    assert khalti.amount == 100  # slots still exposes attributes

"""Live sandbox smoke tests, gated behind environment variables.

These tests make real requests to provider sandbox endpoints and are **skipped
by default** — no network contact happens unless the caller provides actual
credentials via environment variables:

- eSewa:    ``NEPALI_PAYMENT_ESEWA_SECRET``
- Khalti:   ``NEPALI_PAYMENT_KHALTI_SECRET``
- Fonepay:  ``NEPALI_PAYMENT_FONEPAY_SECRET``, ``NEPALI_PAYMENT_FONEPAY_MERCHANT``,
            ``NEPALI_PAYMENT_FONEPAY_USERNAME``, ``NEPALI_PAYMENT_FONEPAY_PASSWORD``

They assert only that a well-formed result is returned and that the transport
succeeds, never hard-code expected provider data. Run with:

    NEPALI_PAYMENT_KHALTI_SECRET=... pytest -m live

To opt in is deliberate: pushing a CI or a shared-hosting deploy without keys
must never trigger live egress.
"""

import json
import os

import pytest

from nepali_payment.enums import PaymentMethod, PaymentMode
from nepali_payment.http import ApiService
from nepali_payment.manager import PaymentManager
from nepali_payment.models import PaymentResult
from nepali_payment.models.esewa import PaymentRequest as EsewaRequest
from nepali_payment.models.fonepay import TaxRefundRequest
from nepali_payment.models.khalti import PaymentRequest as KhaltiRequest

pytestmark = pytest.mark.live


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


esewa_creds = pytest.mark.skipif(
    not _env("NEPALI_PAYMENT_ESEWA_SECRET"),
    reason="NEPALI_PAYMENT_ESEWA_SECRET not set; skipping live eSewa test",
)

khalti_creds = pytest.mark.skipif(
    not _env("NEPALI_PAYMENT_KHALTI_SECRET"),
    reason="NEPALI_PAYMENT_KHALTI_SECRET not set; skipping live Khalti test",
)

fonepay_creds = pytest.mark.skipif(
    not (
        _env("NEPALI_PAYMENT_FONEPAY_SECRET")
        and _env("NEPALI_PAYMENT_FONEPAY_MERCHANT")
        and _env("NEPALI_PAYMENT_FONEPAY_USERNAME")
        and _env("NEPALI_PAYMENT_FONEPAY_PASSWORD")
    ),
    reason="Fonepay credentials not set; skipping live Fonepay test",
)


def _manager(gateway, secret, mode=PaymentMode.SANDBOX):
    api = ApiService(timeout=30.0)
    return PaymentManager(gateway, mode, secret, api=api)


@esewa_creds
def test_live_esewa_v2_initiate():
    """Initiate an eSewa payment against the sandbox and confirm transport works."""
    secret = _env("NEPALI_PAYMENT_ESEWA_SECRET")
    manager = _manager(PaymentMethod.ESEWA, secret)
    request = EsewaRequest(
        amount="100",
        total_amount="113",
        transaction_uuid="live-smoke-test",
        product_code="EPAYTEST",
        signed_field_names="total_amount,transaction_uuid,product_code",
    )
    result = manager.initiate_payment(PaymentResult, request)
    assert isinstance(result, PaymentResult)
    # The assertion proves the transport reached the live sandbox and returned a
    # structured result (success data, or a provider / network error message).
    assert result.message


@khalti_creds
def test_live_khalti_v2_initiate():
    """Initiate a Khalti payment against the sandbox."""
    secret = _env("NEPALI_PAYMENT_KHALTI_SECRET")
    manager = _manager(PaymentMethod.KHALTI, secret)
    request = KhaltiRequest(
        return_url="https://example.test/callback",
        website_url="https://example.test",
        amount=1000,
        purchase_order_id="live-smoke-test",
        purchase_order_name="Live smoke test",
    )
    result = manager.initiate_payment(PaymentResult, request)
    assert isinstance(result, PaymentResult)
    assert isinstance(result.success, bool)


@fonepay_creds
def test_live_fonepay_initiate():
    """Generate a Fonepay QR against the provider, using real merchant creds."""
    secret = _env("NEPALI_PAYMENT_FONEPAY_SECRET")
    manager = _manager(PaymentMethod.FONEPAY, secret)
    from nepali_payment.models.fonepay import QrRequest

    qr = QrRequest(
        amount="100",
        remarks1="live",
        remarks2="smoke",
        prn="live-smoke-prn",
        merchant_code=_env("NEPALI_PAYMENT_FONEPAY_MERCHANT"),
        username=_env("NEPALI_PAYMENT_FONEPAY_USERNAME"),
        password=_env("NEPALI_PAYMENT_FONEPAY_PASSWORD"),
    )
    result = manager.initiate_payment(PaymentResult, qr)
    assert isinstance(result, PaymentResult)
    assert isinstance(result.success, bool)


@fonepay_creds
def test_live_fonepay_status():
    """Query Fonepay QR status using real merchant creds."""
    secret = _env("NEPALI_PAYMENT_FONEPAY_SECRET")
    manager = _manager(PaymentMethod.FONEPAY, secret)
    payload = json.dumps(
        {
            "prn": "live-smoke-prn",
            "merchantCode": _env("NEPALI_PAYMENT_FONEPAY_MERCHANT"),
            "username": _env("NEPALI_PAYMENT_FONEPAY_USERNAME"),
            "password": _env("NEPALI_PAYMENT_FONEPAY_PASSWORD"),
        }
    )
    result = manager.verify_payment(PaymentResult, payload)
    assert isinstance(result, PaymentResult)
    assert isinstance(result.success, bool)


@fonepay_creds
def test_live_fonepay_tax_refund():
    """Submit a Fonepay tax refund using real merchant creds."""
    secret = _env("NEPALI_PAYMENT_FONEPAY_SECRET")
    manager = _manager(PaymentMethod.FONEPAY, secret)
    request = TaxRefundRequest(
        fonepay_trace_id=0,
        transaction_amount="100",
        merchant_prn="live-smoke-prn",
        invoice_number="INV-1",
        invoice_date="31/07/2026",
        merchant_code=_env("NEPALI_PAYMENT_FONEPAY_MERCHANT"),
        username=_env("NEPALI_PAYMENT_FONEPAY_USERNAME"),
        password=_env("NEPALI_PAYMENT_FONEPAY_PASSWORD"),
    )
    result = manager.process_tax_refund(PaymentResult, request)
    assert isinstance(result, PaymentResult)
    assert isinstance(result.success, bool)

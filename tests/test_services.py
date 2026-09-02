"""Gateway service integration tests with mocked HTTP (constitution II)."""

import base64
import json

import pytest
import requests

from nepali_payment.enums import PaymentMethod, PaymentMode
from nepali_payment.exceptions import PaymentError
from nepali_payment.helpers import convert_to
from nepali_payment.http import ApiService
from nepali_payment.manager import PaymentManager
from nepali_payment.models import PaymentResult
from nepali_payment.models.esewa import PaymentRequest as EsewaRequest
from nepali_payment.models.fonepay import QrRequest, QrResponse, StaticQrRequest, TaxRefundRequest
from nepali_payment.models.khalti import PaymentRequest as KhaltiRequest
from nepali_payment.service_factory import get_payment_service

SECRET_KEY = "a7e3512f5032480a83137793cb2021dc"


class FakeResponse:
    def __init__(self, payload, status=200, content_type="application/json", url="https://example.test/x"):
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.url = url
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self._payload, str):
            raise TypeError("not json")
        return self._payload

    @property
    def ok(self):
        return 200 <= self.status_code < 300


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.last_kwargs = None

    def request(self, method, url, headers=None, data=None, json=None, timeout=None):
        self.last_kwargs = {"method": method, "url": url, "headers": headers, "data": data, "json": json}
        return self.responses.pop(0)


def test_esewa_v2_initiate_form_encoded_signature_and_endpoint():
    session = FakeSession([FakeResponse("https://epay/redirect", content_type="text/html")])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.ESEWA, PaymentMode.SANDBOX, SECRET_KEY, api=api)

    request = EsewaRequest(
        amount="100",
        total_amount="113",
        transaction_uuid="uuid-1",
        product_code="EPAYTEST",
        signed_field_names="total_amount,transaction_uuid,product_code",
    )
    result = manager.initiate_payment(PaymentResult, request)

    assert result.success is True
    assert result.data is not None
    assert session.last_kwargs["url"] == "https://rc-epay.esewa.com.np/api/epay/main/v2/form"
    assert session.last_kwargs["method"] == "POST"
    assert session.last_kwargs["data"]["transaction_uuid"] == "uuid-1"
    assert request.signature  # signature was generated


def test_esewa_verify_maps_status_to_success():
    manager = PaymentManager(PaymentMethod.ESEWA, PaymentMode.SANDBOX, SECRET_KEY)
    base64_content = lambda status: base64.b64encode(
        json.dumps({"status": status, "total_amount": 100.0}).encode()
    ).decode()

    ok = manager.verify_payment(PaymentResult, base64_content("COMPLETE"))
    assert ok.success is True
    assert ok.data.status == "COMPLETE"

    cancelled = manager.verify_payment(PaymentResult, base64_content("CANCELLED"))
    assert cancelled.success is False
    assert cancelled.data.status == "CANCELLED"

    failed = manager.verify_payment(PaymentResult, base64_content("FAILED"))
    assert failed.success is False
    assert failed.data.status == "FAILED"


def test_esewa_service_direct_empty_and_malformed_content():
    """Cover eSewa's own guards reached by calling the service directly."""
    from nepali_payment.services.esewa import PaymentService as EsewaService

    svc = EsewaService("secret", PaymentMode.SANDBOX)
    with pytest.raises(ValueError):
        svc.verify_payment(PaymentResult, "")
    with pytest.raises(PaymentError):
        # JSON decodes to a list, so PaymentResponse(**list) fails -> wrapped in PaymentError.
        svc.verify_payment(PaymentResult, base64.b64encode(b"[1,2,3]").decode())


def test_esewa_initiate_with_wrong_content_type_raises_type_error():
    manager = PaymentManager(PaymentMethod.ESEWA, PaymentMode.SANDBOX, SECRET_KEY)
    req = KhaltiRequest(return_url="https://return", website_url="https://site", amount=100)
    with pytest.raises(TypeError):
        manager.initiate_payment(PaymentResult, req)


def test_esewa_raises_payment_error_not_failed_result_on_failure():
    """eSewa's distinct contract: a network failure raises, it does not fold."""

    class _BadSession:
        def request(self, **kwargs):
            raise requests.ConnectionError("offline")

    api = ApiService(session=_BadSession())
    manager = PaymentManager(PaymentMethod.ESEWA, PaymentMode.SANDBOX, SECRET_KEY, api=api)
    req = EsewaRequest(
        amount="100",
        total_amount="113",
        transaction_uuid="uuid-1",
        product_code="EPAYTEST",
        signed_field_names="total_amount,transaction_uuid,product_code",
    )
    with pytest.raises(PaymentError):
        manager.initiate_payment(PaymentResult, req)


def test_esewa_passthrough_preserves_payment_error_type():
    """A ProviderError (a PaymentError) from the HTTP layer must be re-raised."""

    class _Resp:
        ok = False
        status_code = 500
        text = "Internal error"
        url = "https://epay/x"

        def __init__(self):
            self.headers = {"Content-Type": "application/json"}

    class _BadSession:
        def request(self, **kwargs):
            return _Resp()

    api = ApiService(session=_BadSession())
    manager = PaymentManager(PaymentMethod.ESEWA, PaymentMode.SANDBOX, SECRET_KEY, api=api)
    req = EsewaRequest(
        amount="100",
        total_amount="113",
        transaction_uuid="uuid-1",
        product_code="EPAYTEST",
        signed_field_names="total_amount,transaction_uuid,product_code",
    )
    with pytest.raises(PaymentError):
        manager.initiate_payment(PaymentResult, req)


def test_esewa_verify_with_empty_content_raises_value_error():
    from nepali_payment.exceptions import ValidationError

    manager = PaymentManager(PaymentMethod.ESEWA, PaymentMode.SANDBOX, SECRET_KEY)
    with pytest.raises(ValidationError):
        manager.verify_payment(PaymentResult, "")


def test_service_factory_raises_on_unsupported_gateway():
    from nepali_payment.exceptions import UnsupportedGatewayError

    with pytest.raises(UnsupportedGatewayError):
        get_payment_service("NotAGateway", SECRET_KEY, PaymentMode.SANDBOX)


def test_service_factory_requires_secret_key():
    with pytest.raises(ValueError):
        get_payment_service(PaymentMethod.KHALTI, "", PaymentMode.SANDBOX)


def test_endpoint_for_raises_on_unsupported_gateway_or_action():
    from nepali_payment.enums import PaymentAction
    from nepali_payment.exceptions import UnsupportedGatewayError
    from nepali_payment.factory import _endpoint_for

    with pytest.raises(UnsupportedGatewayError):
        _endpoint_for("NotAGateway", PaymentAction.PROCESS_PAYMENT, PaymentMode.SANDBOX)
    with pytest.raises(UnsupportedGatewayError):
        # Fonepay has no CHECK_PAYMENT mapping in the endpoint registry.
        _endpoint_for(PaymentMethod.FONEPAY, PaymentAction.CHECK_PAYMENT, PaymentMode.SANDBOX)


def test_khalti_service_requires_secret_key():
    from nepali_payment.services.khalti import PaymentService as KhaltiService

    with pytest.raises(ValueError):
        KhaltiService("", PaymentMode.SANDBOX)


def test_fonepay_service_requires_secret_key():
    from nepali_payment.services.fonepay import PaymentService as FonepayService

    with pytest.raises(ValueError):
        FonepayService("", PaymentMode.SANDBOX)


def test_esewa_service_requires_secret_key():
    from nepali_payment.services.esewa import PaymentService as EsewaService

    with pytest.raises(ValueError):
        EsewaService("", PaymentMode.SANDBOX)


def test_manager_requires_secret_key():
    from nepali_payment.manager import PaymentManager

    with pytest.raises(ValueError):
        PaymentManager(PaymentMethod.KHALTI, PaymentMode.SANDBOX, "")


def test_khalti_v2_initiate_authorization_header_and_json_body():
    khalti_response = {"pidx": "abc123", "payment_url": "https://pay.khalti/...", "expires_in": 30}
    session = FakeSession([FakeResponse(khalti_response)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.KHALTI, PaymentMode.SANDBOX, SECRET_KEY, api=api)

    request = KhaltiRequest(return_url="https://return", website_url="https://site", amount=100)
    result = manager.initiate_payment(PaymentResult, request)

    assert result.success is True
    assert result.data.pidx == "abc123"
    assert session.last_kwargs["url"] == "https://a.khalti.com/api/epayment/initiate/"
    assert session.last_kwargs["headers"]["Authorization"].startswith("key ")
    assert session.last_kwargs["json"]["return_url"] == "https://return"


def test_khalti_v2_verify_form_encoding_with_pidx():
    verify_response = {
        "pidx": "abc123",
        "total_amount": 100,
        "status": "Completed",
        "transaction_id": "txn",
        "fee": 3,
        "refunded": False,
    }
    session = FakeSession([FakeResponse(verify_response)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.KHALTI, PaymentMode.SANDBOX, SECRET_KEY, api=api)

    result = manager.verify_payment(PaymentResult, "abc123")

    assert result.success is True
    assert result.data.status == "Completed"
    assert session.last_kwargs["url"] == "https://a.khalti.com/api/epayment/lookup/"
    assert session.last_kwargs["data"] == {"pidx": "abc123"}


def test_fonepay_initiate_hmac_sha512_hex_data_validation():
    qr_response = {
        "message": "ok",
        "qrMessage": "QRDATA",
        "status": "success",
        "success": True,
        "thirdpartyQrWebSocketUrl": "wss://foo",
    }
    session = FakeSession([FakeResponse(qr_response)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.FONEPAY, PaymentMode.SANDBOX, SECRET_KEY, api=api)

    request = QrRequest(
        amount="14",
        remarks1="test1",
        remarks2="test2",
        prn="prn-1",
        merchant_code="NBQM",
        username="u",
        password="p",
    )
    result = manager.initiate_payment(PaymentResult, request)

    assert result.success is True
    assert result.data.qr_message == "QRDATA"
    assert session.last_kwargs["url"].endswith("thirdPartyDynamicQrDownload")
    body = session.last_kwargs["json"]
    assert len(body["dataValidation"]) == 128
    assert body["merchantCode"] == "NBQM"


def test_fonepay_verify_hmac_sha512_status():
    status_response = {"fonepayTraceId": 123, "paymentStatus": "Paid", "prn": "prn-1"}
    session = FakeSession([FakeResponse(status_response)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.FONEPAY, PaymentMode.SANDBOX, SECRET_KEY, api=api)

    content = json.dumps({"prn": "prn-1", "merchantCode": "NBQM", "username": "u", "password": "p"})
    result = manager.verify_payment(PaymentResult, content)

    assert result.success is True
    assert result.data.payment_status == "Paid"
    assert len(session.last_kwargs["json"]["dataValidation"]) == 128


def test_fonepay_tax_refund():
    refund_response = {"fonepayTraceId": 35132, "message": "ok", "success": True}
    session = FakeSession([FakeResponse(refund_response)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.FONEPAY, PaymentMode.SANDBOX, SECRET_KEY, api=api)

    request = TaxRefundRequest(
        fonepay_trace_id=35132,
        transaction_amount="100",
        merchant_prn="PRN",
        invoice_number="INV",
        invoice_date="2076.09.29",
        merchant_code="NBQM",
    )
    result = manager.process_tax_refund(PaymentResult, request)

    assert result.success is True
    assert len(session.last_kwargs["json"]["dataValidation"]) == 128


def test_fonepay_static_qr():
    static_response = {"qrMessage": "STATICQRDATA"}
    session = FakeSession([FakeResponse(static_response)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.FONEPAY, PaymentMode.SANDBOX, SECRET_KEY, api=api)

    request = StaticQrRequest(
        prn="prn-static",
        merchant_code="NBQM",
        username="u",
        password="p",
    )
    result = manager.process_static_qr(PaymentResult, request)

    assert result.success is True
    assert result.data.qr_message == "STATICQRDATA"
    assert session.last_kwargs["url"].endswith("thirdPartyStaticQrDownload")
    body = session.last_kwargs["json"]
    assert len(body["dataValidation"]) == 128
    assert body["merchantCode"] == "NBQM"
    assert body["prn"] == "prn-static"


def test_fonepay_static_qr_rejects_wrong_type():
    session = FakeSession([])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.FONEPAY, PaymentMode.SANDBOX, SECRET_KEY, api=api)
    with pytest.raises(TypeError):
        manager.process_static_qr(PaymentResult, {})


def test_static_qr_only_supported_for_fonepay():
    session = FakeSession([])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.KHALTI, PaymentMode.SANDBOX, SECRET_KEY, api=api)
    with pytest.raises(Exception) as excinfo:
        manager.process_static_qr(PaymentResult, StaticQrRequest(merchant_code="NBQM"))
    assert "only supported for Fonepay" in str(excinfo.value)


def test_convert_to_builds_dataclass_from_dict():

    obj = convert_to(QrResponse, {"message": "hi", "success": True})
    assert obj.message == "hi"
    assert obj.success is True


def test_manager_reuses_single_session_across_operations():
    """The manager must not open a fresh connection per call (N+1 sessions).

    When no ApiService is injected, PaymentManager lazily creates one shared
    ApiService and reuses it (and its underlying requests.Session) for every
    initiate/verify/tax-refund operation instead of building a new session per
    call.
    """
    manager = PaymentManager(PaymentMethod.FONEPAY, PaymentMode.SANDBOX, SECRET_KEY)

    api1 = manager._api_service()
    api2 = manager._api_service()
    assert api1 is api2, "manager must cache a single ApiService across calls"
    # Both operations flow through the same shared session object.
    service = get_payment_service(PaymentMethod.FONEPAY, SECRET_KEY, PaymentMode.SANDBOX, api=api1)
    assert service._api_service is api1

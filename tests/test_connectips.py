"""ConnectIPS service tests with a real RSA key and mocked HTTP."""

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from nepali_payment.enums import PaymentMethod, PaymentMode
from nepali_payment.http import ApiService
from nepali_payment.manager import PaymentManager
from nepali_payment.models import PaymentResult
from nepali_payment.models.connectips import PaymentRequest, VerificationRequest
from nepali_payment.services.connectips import ConnectIpsConfig, PaymentService


def _make_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.fixture(scope="module")
def key():
    yield _make_key()


@pytest.fixture
def config(key):
    cfg = ConnectIpsConfig(
        merchant_id="MERCHANT1",
        app_id="APP1",
        app_name="Demo App",
        app_password="secret",
        success_url="https://example.com/success",
        failure_url="https://example.com/failure",
    )
    cfg._private_key = key
    return cfg


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


def test_connectips_initiate_builds_form_fields(config):
    session = FakeSession([])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.CONNECTIPS, PaymentMode.SANDBOX, "", api=api, config=config)

    request = PaymentRequest(order_id="ORD-1", amount=12500, description="Test order")
    result = manager.initiate_payment(PaymentResult, request)

    assert result.success is True
    assert result.data.target_url == "https://uat.connectips.com/connectipswebgw/loginpage"
    fields = result.data.form_fields
    assert fields["MERCHANTID"] == "MERCHANT1"
    assert fields["APPID"] == "APP1"
    assert fields["TXNID"] == "ORD-1"
    assert fields["TXNAMT"] == "12500"
    assert fields["TXNDATE"]  # DD-MM-YYYY
    assert fields["SUCCESSURL"] == "https://example.com/success"
    assert fields["TOKEN"]  # RSA-signed


def test_connectips_verify_success(config):
    response_payload = {
        "status": "SUCCESS",
        "status_desc": "Success",
        "trans_ref_id": "REF1",
        "reference_id": "ORD-1",
        "txn_amount": 12500,
        "txn_date": "31-08-2026",
    }
    session = FakeSession([FakeResponse(response_payload)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.CONNECTIPS, PaymentMode.SANDBOX, "", api=api, config=config)

    result = manager.verify_payment(PaymentResult, json.dumps({"TXNID": "ORD-1", "expectedAmount": 12500}))

    assert result.success is True
    assert result.data.status == "COMPLETE"
    assert result.data.trans_ref_id == "REF1"
    assert session.last_kwargs["url"] == "https://uat.connectips.com/connectipswebws/api/creditor/validatetxn"
    assert session.last_kwargs["headers"]["Authorization"].startswith("Basic ")
    body = session.last_kwargs["json"]
    assert body["MerchantID"] == "MERCHANT1"
    assert body["ReferenceID"] == "ORD-1"
    assert body["TxnAmount"] == 12500
    assert body["Token"]


def test_connectips_verify_cancelled_skips_api(config):
    session = FakeSession([])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.CONNECTIPS, PaymentMode.SANDBOX, "", api=api, config=config)

    result = manager.verify_payment(
        PaymentResult, json.dumps({"TXNID": "ORD-1", "STATUS": "CANCELLED", "expectedAmount": 100})
    )

    assert result.success is False
    assert len(session.responses) == 0  # no validation API call


def test_connectips_verify_not_found(config):
    response_payload = {"status": "NOT_FOUND", "status_desc": "Not found"}
    session = FakeSession([FakeResponse(response_payload)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.CONNECTIPS, PaymentMode.SANDBOX, "", api=api, config=config)

    result = manager.verify_payment(PaymentResult, json.dumps({"TXNID": "ORD-MISSING", "expectedAmount": 100}))
    assert result.success is False


def test_connectips_requires_config(config, key):
    bad = ConnectIpsConfig(app_id="APP1", cert_data=_pem(key), cert_format="pem")
    with pytest.raises(Exception) as excinfo:
        PaymentService(bad, PaymentMode.SANDBOX)
    assert "merchant_id" in str(excinfo.value)


def test_connectips_wrong_type_rejected(config):
    manager = PaymentManager(PaymentMethod.CONNECTIPS, PaymentMode.SANDBOX, "", config=config)
    with pytest.raises(TypeError):
        manager.initiate_payment(PaymentResult, {})


def test_verification_request_to_dict_uses_pascal_case():
    request = VerificationRequest(merchant_id="M", app_id="A", reference_id="R", txn_amount=100, token="T")
    assert request.to_dict() == {
        "MerchantID": "M",
        "AppID": "A",
        "ReferenceID": "R",
        "TxnAmount": 100,
        "Token": "T",
    }


def test_load_rsa_private_key_from_pem_data():
    from nepali_payment.helpers import load_rsa_private_key

    key = load_rsa_private_key(cert_data=_pem(_make_key()), cert_format="pem")
    assert key


def test_load_rsa_private_key_requires_source():
    from nepali_payment.exceptions import ValidationError
    from nepali_payment.helpers import load_rsa_private_key

    with pytest.raises(ValidationError):
        load_rsa_private_key()


def test_rsa_signature_verifies_with_public_key(key):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    from nepali_payment.helpers import generate_rsa_signature

    message = "MERCHANT1,APP1,ORD-1,100,31-08-2026"
    signature = generate_rsa_signature(message, key)
    key.public_key().verify(
        base64.b64decode(signature),
        message.encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_connectips_verify_amount_mismatch_fails(config):
    response_payload = {
        "status": "SUCCESS",
        "status_desc": "Success",
        "trans_ref_id": "REF1",
        "reference_id": "ORD-1",
        "txn_amount": 9999,
    }
    session = FakeSession([FakeResponse(response_payload)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.CONNECTIPS, PaymentMode.SANDBOX, "", api=api, config=config)
    result = manager.verify_payment(PaymentResult, json.dumps({"TXNID": "ORD-1", "expectedAmount": 12500}))
    assert result.success is False
    assert "Expected amount" in result.message


def _service(pem_data, payment_mode=PaymentMode.SANDBOX, **overrides):
    cfg = ConnectIpsConfig(
        merchant_id="MERCHANT1",
        app_id="APP1",
        cert_data=pem_data,
        cert_format="pem",
        **overrides,
    )
    return PaymentService(cfg, payment_mode)


def test_connectips_config_validation(key):
    pem = _pem(key)
    PaymentService(ConnectIpsConfig(merchant_id="M", app_id="A", cert_data=pem, cert_format="pem"), PaymentMode.SANDBOX)
    PaymentService(
        ConnectIpsConfig(merchant_id="M", app_id="A", cert_data=pem, cert_format="pem"), PaymentMode.PRODUCTION
    )
    with pytest.raises(Exception) as excinfo:
        PaymentService(ConnectIpsConfig(app_id="A", cert_data=pem, cert_format="pem"), PaymentMode.SANDBOX)
    assert "merchant_id" in str(excinfo.value)
    with pytest.raises(Exception) as excinfo:
        PaymentService(ConnectIpsConfig(merchant_id="M", cert_data=pem, cert_format="pem"), PaymentMode.SANDBOX)
    assert "app_id" in str(excinfo.value)
    with pytest.raises(Exception) as excinfo:
        PaymentService(ConnectIpsConfig(merchant_id="M", app_id="A"), PaymentMode.SANDBOX)
    assert "cert" in str(excinfo.value)


def test_connectips_initiate_validation(key):
    config = ConnectIpsConfig(merchant_id="M", app_id="A", cert_data=_pem(key), cert_format="pem")
    svc = PaymentService(config, PaymentMode.SANDBOX)
    for bad in [
        PaymentRequest(order_id="O", amount=0),
        PaymentRequest(order_id="O", amount=-100),
        PaymentRequest(amount=100),
        PaymentRequest(order_id="O", amount=100),
    ]:
        result = svc.initiate_payment(PaymentResult, bad)
        assert result.success is False


def test_connectips_token_reproducible(config, key):
    svc = PaymentService(config, PaymentMode.SANDBOX)
    t1 = svc._generate_initiate_token("ORD-1", 1000, "14-01-2026")
    t2 = svc._generate_initiate_token("ORD-1", 1000, "14-01-2026")
    t3 = svc._generate_initiate_token("ORD-1x", 1000, "14-01-2026")
    assert t1 == t2
    assert t1 != t3
    assert t1  # non-empty


def test_connectips_verify_invalid_token(config):
    response_payload = {"status": "INVALID_TOKEN", "token_valid": False}
    session = FakeSession([FakeResponse(response_payload)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.CONNECTIPS, PaymentMode.SANDBOX, "", api=api, config=config)
    result = manager.verify_payment(PaymentResult, json.dumps({"TXNID": "ORD-1", "expectedAmount": 100}))
    assert result.success is False


def test_connectips_verify_missing_txnid(config):
    session = FakeSession([])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.CONNECTIPS, PaymentMode.SANDBOX, "", api=api, config=config)
    result = manager.verify_payment(PaymentResult, json.dumps({}))
    assert result.success is False
    assert len(session.responses) == 0


def test_connectips_verify_server_error(config):
    session = FakeSession([FakeResponse({"error": "boom"}, status=500)])
    api = ApiService(session=session)
    manager = PaymentManager(PaymentMethod.CONNECTIPS, PaymentMode.SANDBOX, "", api=api, config=config)
    result = manager.verify_payment(PaymentResult, json.dumps({"TXNID": "ORD-1", "expectedAmount": 100}))
    assert result.success is False


def test_connectips_status_normalization():
    from nepali_payment.services.connectips import normalize_status

    assert normalize_status("SUCCESS") == "COMPLETE"
    assert normalize_status("PENDING") == "PENDING"
    assert normalize_status("CANCELLED") == "CANCELLED"
    assert normalize_status("TIMEOUT") == "EXPIRED"
    assert normalize_status("SESSION_EXPIRED") == "EXPIRED"
    assert normalize_status("FAILED") == "FAILED"
    assert normalize_status("NOT_FOUND") == "FAILED"
    assert normalize_status("INVALID_TOKEN") == "FAILED"
    assert normalize_status("UNKNOWN") == "FAILED"

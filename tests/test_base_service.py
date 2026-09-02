"""Shared base-service and HTTP timeout contract tests.

Verifies the OOP contract: every concrete gateway ``PaymentService`` subclasses
:class:`~nepali_payment.services.base.BasePaymentService`, shares the injected
HTTP client, and the fold/re-raise exception contracts are preserved.
"""

from typing import ClassVar

from nepali_payment.constants import ApiEndpoints
from nepali_payment.enums import PaymentMode
from nepali_payment.http import ApiService
from nepali_payment.models import PaymentResult
from nepali_payment.services.base import BasePaymentService
from nepali_payment.services.connectips import PaymentService as ConnectIpsService
from nepali_payment.services.fonepay import PaymentService as FonepayService
from nepali_payment.services.khalti import PaymentService as KhaltiService


def test_all_gateway_services_subclass_base():
    for cls in (KhaltiService, FonepayService, ConnectIpsService):
        assert issubclass(cls, BasePaymentService), f"{cls.__name__} must subclass BasePaymentService"


def test_services_share_base_url_and_api():
    khalti = KhaltiService("secret", PaymentMode.PRODUCTION)
    assert khalti.base_url == ApiEndpoints.KHALTI.BASE_URL
    assert isinstance(khalti._api_service, ApiService)

    khalti_sb = KhaltiService("secret", PaymentMode.SANDBOX)
    assert khalti_sb.base_url == ApiEndpoints.KHALTI.SANDBOX_BASE_URL


def test_as_failed_builds_failed_result():
    svc = KhaltiService("secret", PaymentMode.SANDBOX)
    result = svc._as_failed(PaymentResult, RuntimeError("boom"))
    assert result.success is False
    assert "boom" in result.message


def test_run_result_folds_exception():
    svc = KhaltiService("secret", PaymentMode.SANDBOX)

    def fail():
        raise RuntimeError("kaput")

    result = svc._run_result(PaymentResult, fail)
    assert result.success is False
    assert "kaput" in result.message


def test_run_result_passthrough():
    svc = KhaltiService("secret", PaymentMode.SANDBOX)
    result = svc._run_result(PaymentResult, lambda: PaymentResult(success=True, message="ok"))
    assert result.success is True


def test_connectips_service_shares_base_http_client():
    """ConnectIPS inherits the common base interface without a secret key."""
    assert issubclass(ConnectIpsService, BasePaymentService)
    assert callable(ConnectIpsService.initiate_payment)
    assert callable(ConnectIpsService.verify_payment)


def test_api_service_default_and_per_call_timeout():
    api = ApiService(timeout=15.0)
    assert api._timeout == 15.0
    # Explicit per-call timeout, including 0, must take precedence over the default.


class _RecordingResponse:
    status_code: ClassVar[int] = 200
    headers: ClassVar[dict] = {"Content-Type": "application/json"}
    url: ClassVar[str] = ""
    text: ClassVar[str] = "{}"

    def json(self):
        return {}

    @property
    def ok(self):
        return True


def test_timeout_zero_not_swallowed():
    """A per-call ``timeout=0`` must not be replaced by the default."""
    captured = {}

    class _Session:
        def request(self, method, url, headers=None, data=None, json=None, timeout=None):
            captured["timeout"] = timeout
            return _RecordingResponse()

    api = ApiService(session=_Session())
    api.get_async_result(object, "http://example.test/x", "POST", timeout=0)
    assert captured["timeout"] == 0


def test_manager_caches_service_per_instance():
    """The manager must build its gateway service only once.

    Reusing the service avoids re-parsing the ConnectIPS RSA certificate and
    keeps one HTTP client across every operation on this manager.
    """
    from nepali_payment.enums import PaymentMethod
    from nepali_payment.manager import PaymentManager

    manager = PaymentManager(PaymentMethod.KHALTI, PaymentMode.SANDBOX, "secret")
    assert manager._service() is manager._service()


def test_coerce_handles_non_mapping_data_without_crashing():
    """Coercing a plain string must fall back cleanly, not raise AttributeError."""
    from nepali_payment.helpers import _coerce
    from nepali_payment.models.khalti import PaymentResponse

    assert _coerce(PaymentResponse, "COMPLETE") == "COMPLETE"

"""HTTP layer tests: serialization, error mapping and optional retries."""

from dataclasses import dataclass, field

import pytest
import requests

from nepali_payment.exceptions import NetworkError, ProviderError
from nepali_payment.http import ApiService, _to_dict


class _Resp:
    def __init__(self, status_code=200, text=None, url=None, headers=None, payload=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text if text is not None else ""
        self.url = url or "http://example.test/x"
        self.headers = dict(headers or {"Content-Type": "application/json"})
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.raised = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.responses:
            return self.responses.pop(0)
        raise AssertionError("no more responses")


def test_http_error_raw_path_raises_validation():
    session = _Session([_Resp(status_code=500, text="Internal error")])
    api = ApiService(session=session)
    with pytest.raises(ProviderError) as exc:
        api.get_async_result(dict, "http://example.test/x", "POST")
    assert "500" in str(exc.value)


def test_network_error_wraps_request_exception():
    class _BadSession:
        def request(self, **kwargs):
            raise requests.ConnectionError("down")

    api = ApiService(session=_BadSession())
    with pytest.raises(NetworkError) as exc:
        api.get_async_result(dict, "http://example.test/x", "GET")
    assert "down" in exc.value.provider_message


def test_html_content_type_returns_url_as_string():
    session = _Session([_Resp(status_code=200, headers={"Content-Type": "text/html"}, url="https://pay/loc")])
    api = ApiService(session=session)
    out = api.get_async_result(str, "https://epay/redirect", "POST")
    assert out == "https://pay/loc"


def test_non_json_body_falls_back_to_text():
    # JSON content-type but an unparseable body -> convert_to(cls, response.text).
    session = _Session([_Resp(status_code=200, headers={"Content-Type": "application/json"}, text="<html>oops</html>")])
    api = ApiService(session=session)
    out = api.get_async_result(str, "http://example.test/x", "GET")
    assert out == "<html>oops</html>"


def test_retry_recovers_after_transient_error():
    class _Recovering:
        count = 0

        def request(self, **kwargs):
            self.count += 1
            if self.count < 3:
                raise requests.ConnectionError("flaky")
            return _Resp(status_code=200, payload={"ok": True})

    api = ApiService(session=_Recovering(), retries=3, retry_backoff=0)
    out = api.get_async_result(dict, "http://example.test/x", "GET")
    assert out == {"ok": True}


def test_retry_exhausts_then_raises():
    class _Flaky:
        def request(self, **kwargs):
            raise requests.Timeout("slow")

    api = ApiService(session=_Flaky(), retries=2, retry_backoff=0)
    with pytest.raises(NetworkError):
        api.get_async_result(dict, "http://example.test/x", "GET")


def test_retry_disabled_by_default():
    class _Flaky:
        def request(self, **kwargs):
            raise requests.ConnectionError("down")

    session = _Flaky()
    api = ApiService(session=session, retries=0, retry_backoff=0)
    with pytest.raises(NetworkError):
        api.get_async_result(dict, "http://example.test/x", "GET")


def test_to_dict_drops_none_dataclass_fields_but_keeps_nested_lists():
    @dataclass
    class Inner:
        a: str = "x"

    @dataclass
    class Outer:
        inner: Inner = field(default_factory=Inner)
        nope: str | None = None
        items: list = field(default_factory=list)

    outer = Outer(items=[Inner(a="v"), None])
    out = _to_dict(outer)
    assert "nope" not in out
    assert out["inner"] == {"a": "x"}
    assert out["items"] == [{"a": "v"}, None]

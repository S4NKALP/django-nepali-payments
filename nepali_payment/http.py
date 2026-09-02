import time
from dataclasses import asdict, is_dataclass
from typing import Any, TypeVar

import requests

from nepali_payment.exceptions import NetworkError, ProviderError
from nepali_payment.helpers import convert_to

T = TypeVar("T")


def _to_dict(obj: Any) -> Any:
    """Serialize (nested) dataclasses to plain dicts for JSON output."""
    if is_dataclass(obj):
        return {k: _to_dict(v) for k, v in asdict(obj).items() if v is not None}
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(v) for v in obj]
    return obj


#: HTTP statuses that indicate a transient server problem worth retrying.
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


def _should_retry_exception(exc: requests.RequestException) -> bool:
    """Return whether a raised request error is a transient transport failure."""
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


class ApiService:
    """Makes HTTP requests to the providers and turns their responses into objects."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = 15.0,
        retries: int = 0,
        retry_backoff: float = 1.0,
    ):
        """Create an ApiService.

        Args:
            session: An optional pre-configured requests Session; a new pooled
                session is created if omitted.
            timeout: Default timeout (seconds) for requests. A per-call
                ``timeout`` passed to :meth:`get_async_result` overrides this.
            retries: How many extra attempts to make after a transient
                transport error or a 5xx response. Zero (the default) never
                retries. Start a payment twice by accident, so only enable this
                if your provider endpoint is safe to repeat.
            retry_backoff: Base seconds to wait between attempts (backoff
                doubles each try). Ignored when ``retries`` is zero.

        """
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout
        self._retries = max(0, int(retries))
        self._retry_backoff = max(0.0, float(retry_backoff))

    def close(self) -> None:
        """Close the underlying HTTP session, releasing pooled connections."""
        self._session.close()

    def get_async_result(
        self,
        cls: type[T],
        api_path: str,
        http_method: str,
        header_param: dict[str, str] | None = None,
        key_value_pairs: dict[str, str] | None = None,
        request_body: Any | None = None,
        timeout: float | None = None,
    ) -> T:
        """Send a request and turn the JSON response into ``cls``."""
        if not api_path:
            raise NetworkError("API path cannot be null or empty.")
        if not http_method:
            raise NetworkError("HTTP method cannot be null.")

        method = http_method.upper()
        headers = {k: v for k, v in (header_param or {}).items() if k.lower() != "content-type"}
        headers.setdefault("Accept", "application/json")

        data: Any | None = None
        json_body: Any | None = None
        if key_value_pairs is not None:
            data = key_value_pairs
        elif request_body is not None:
            json_body = request_body.to_dict() if hasattr(request_body, "to_dict") else _to_dict(request_body)

        attempt = 0
        last_response: requests.Response | None = None

        while True:
            try:
                response = self._session.request(
                    method=method,
                    url=api_path,
                    headers=headers,
                    data=data,
                    json=json_body,
                    timeout=timeout if timeout is not None else self._timeout,
                )
            except requests.RequestException as exc:
                retry = attempt < self._retries and _should_retry_exception(exc)
                if not retry:
                    raise NetworkError(f"Network error during {method} {api_path}: {exc}", str(exc)) from exc
            else:
                last_response = response
                retry = response.status_code in _TRANSIENT_STATUSES and attempt < self._retries

            if not retry:
                break
            attempt += 1
            time.sleep(self._retry_backoff * (2 ** (attempt - 1)))

        if last_response is None:
            raise NetworkError(f"No response during {method} {api_path}")

        response = last_response
        content_type = response.headers.get("Content-Type", "")

        if not response.ok:
            raise ProviderError(
                f"HTTP request failed with status code {response.status_code}. Response: {response.text}",
                response.text,
            )

        if "text/html" in content_type:
            # HTML responses (eSewa redirect) return the request URI as the payment location.
            converted = convert_to(cls, str(response.url))
            return converted  # type: ignore[return-value]

        try:
            parsed = response.json()
        except ValueError:
            return convert_to(cls, response.text)  # type: ignore[return-value]

        return convert_to(cls, parsed)  # type: ignore[return-value]

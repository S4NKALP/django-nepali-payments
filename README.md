# django-nepali-payment

<p align="center">
  <a href="https://github.com/S4NKALP/django-nepali-payments/actions/workflows/ci.yml">
    <img src="https://github.com/S4NKALP/django-nepali-payments/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="https://pypi.org/project/django-nepali-payment/">
    <img src="https://img.shields.io/pypi/v/django-nepali-payment" alt="PyPI version">
  </a>
  <a href="https://pypi.org/project/django-nepali-payment/">
    <img src="https://img.shields.io/pypi/pyversions/django-nepali-payment" alt="Python versions">
  </a>
  <img src="https://img.shields.io/badge/Django-4.2%20%7C%205.0%20%7C%206.0%20%7C%206.1-092E20" alt="Django">
  <a href="https://pypi.org/project/django-nepali-payment/">
    <img src="https://img.shields.io/pypi/dm/django-nepali-payment" alt="PyPI downloads">
  </a>
  <a href="https://github.com/S4NKALP/django-nepali-payments/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/S4NKALP/django-nepali-payments" alt="License">
  </a>
  <a href="https://github.com/S4NKALP/django-nepali-payments">
    <img src="https://img.shields.io/github/last-commit/S4NKALP/django-nepali-payments" alt="Last commit">
  </a>
</p>

Accept Nepal payments from Django with **one consistent API** for Khalti, eSewa,
Fonepay (Dynamic QR, Static QR, status, tax refund) and ConnectIPS. No four
HTTP APIs, no four signing schemes, no four callback formats. One
`PaymentManager`, one `PaymentResult`.

Lightweight: plain HTTPS through a pooled `requests.Session`. No WebSockets, no
async loops, no daemons, and runs on shared hosting.

```bash
pip install django-nepali-payment
# or: uv add django-nepali-payment
```

**Requirements:** Python 3.11+, Django 4.2+, `requests`, `cryptography`
(for ConnectIPS signing).

## Highlights

- **One shape for every gateway**: every call returns a `PaymentResult`.
- **Signatures that just work**: reproduced from each provider's reference:
  - eSewa: HMAC-SHA256 (base64)
  - Fonepay: HMAC-SHA512 (lowercase hex)
  - Khalti: `Authorization: key <secret>` header
  - ConnectIPS: SHA256withRSA over your merchant certificate
- **Sandbox ↔ production in one flag**: flip `PaymentMode`.
- **Shared-hosting-safe polling**: Fonepay settlement checked with a lightweight
  polling thread, not a WebSocket.
- **Fonepay extras built in**: tax refunds and Static QR.
- **Connection reuse**: one shared `requests.Session`, sensible timeouts.
- **Optional retries**: exponential backoff on transient failures; opt in.

## Architecture

Three small layers, all usable directly:

- **`PaymentManager`**: the entry point. Pick gateway, mode, secret once; call
  `initiate_payment` / `verify_payment` (plus Fonepay refund / static QR).
- **Gateway services**: one per provider, extending `BasePaymentService`
  (shared HTTP client, sandbox/prod URL, error handling). Each implements only
  its own initiate/verify logic and signing.
- **Models**: `PaymentResult` is the universal answer type; per-gateway typed
  requests are `dataclass(slots=True)` and self-serialize.

## Quick start

```python
from nepali_payment import PaymentManager, PaymentMethod, PaymentMode, PaymentResult

manager = PaymentManager(
    payment_method=PaymentMethod.ESEWA,   # or KHALTI, FONEPAY
    payment_mode=PaymentMode.SANDBOX,     # switch to PRODUCTION when ready
    secret_key="your-secret-key",
)
```

Every call returns a `PaymentResult`:

| Field        | What it holds                                    |
| ------------ | ------------------------------------------------ |
| `success`    | Did the operation succeed?                       |
| `message`    | Human-readable message (no secrets logged)       |
| `data`       | Gateway-specific response object (may be `None`) |
| `status`     | Reserved; unused (always `200`)                  |
| `error_code` | Reserved; unused (always `None`)                 |

It's truthy like a `bool`, and exposes `raise_for_status()` to raise on failure:

```python
result = manager.initiate_payment(PaymentResult, request).raise_for_status()
print(result.data)   # only reached if the payment actually started
```

### Custom HTTP client

```python
from nepali_payment.http import ApiService

api = ApiService(
    timeout=30.0,        # seconds; default 15
    retries=2,           # retry transient failures (default 0)
    retry_backoff=1.0,   # initial backoff; doubles each attempt
)

manager = PaymentManager(
    PaymentMethod.KHALTI, PaymentMode.SANDBOX,
    secret_key="your-secret-key",
    api=api,
)
```

Call `api.close()` (or `manager._api_service().close()`) to release pooled
connections on shutdown.

> Retries default **off**: re-sending a payment initiation could double-charge.
> Enable only for endpoints safe to repeat.

## Initiate a payment

```python
manager.initiate_payment(PaymentResult, request)
```

### eSewa

```python
from nepali_payment.models.esewa import PaymentRequest as EsewaRequest

request = EsewaRequest(
    amount="100",
    total_amount="113",          # amount + tax + charges
    transaction_uuid="order-123",
    product_code="EPAYTEST",
    signed_field_names="total_amount,transaction_uuid,product_code",
)
result = manager.initiate_payment(PaymentResult, request)
if result.success:
    redirect_url = result.data.payment_url   # send the customer here
```

### Khalti

```python
from nepali_payment.models.khalti import PaymentRequest as KhaltiRequest

request = KhaltiRequest(
    return_url="https://yoursite.com/callback",
    website_url="https://yoursite.com",
    amount=1000,                       # paisa (NPR 10.00)
    purchase_order_id="order-123",
    purchase_order_name="My Order",
)
result = manager.initiate_payment(PaymentResult, request)
if result.success:
    redirect_url = result.data.payment_url   # send the customer here
    pidx = result.data.pidx                  # keep for verification
```

> Khalti amounts are in **paisa** (1 NPR = 100 paisa).

### Fonepay (Dynamic QR)

```python
from nepali_payment.models.fonepay import QrRequest

request = QrRequest(
    amount="100", remarks1="Order 123", remarks2="Main",
    prn="order-123", merchant_code="NBQM",
    username="merchant-user", password="merchant-password",
)
result = manager.initiate_payment(PaymentResult, request)
if result.success:
    qr_data = result.data.qr_message   # show to the customer
```

The dynamic QR bakes the amount in; settlement is async, so pair it with the
[status monitor](#fonepay-qr-status-monitoring).

## Fonepay Static QR

One fixed merchant QR; the customer types the amount at scan. Fetch once per
station:

```python
from nepali_payment.models.fonepay import StaticQrRequest

request = StaticQrRequest(
    prn="merchant-station", merchant_code="NBQM",
    username="merchant-user", password="merchant-password",
)
result = manager.process_static_qr(PaymentResult, request)
if result.success:
    static_qr = result.data.qr_message   # render/print once for this station
```

> `process_static_qr` is Fonepay-only (like the tax refund). On other gateways
> it raises `ValidationError`. For settlement, use `verify_payment` or the
> `FonepayPaymentMonitor` with the payment's PRN.

## ConnectIPS

A **form POST** gateway signed with **SHA256withRSA** using a merchant
certificate (`.pfx`, `.p12` or `.pem`). Instead of a secret key it takes a
config object:

```python
import os
from nepali_payment.enums import PaymentMethod, PaymentMode
from nepali_payment.services.connectips import ConnectIpsConfig

config = ConnectIpsConfig(
    merchant_id="YOUR_MERCHANT_ID",
    app_id="YOUR_APP_ID",
    app_name="Demo App",
    app_password="Your App Password",
    cert_path=os.environ["CONNECTIPS_CERT_PATH"],   # .pfx / .p12 / .pem
    cert_password=os.environ.get("CONNECTIPS_CERT_PASSWORD", ""),
    success_url="https://yoursite.com/payments/success",
    failure_url="https://yoursite.com/payments/failure",
)

manager = PaymentManager(
    payment_method=PaymentMethod.CONNECTIPS,
    payment_mode=PaymentMode.SANDBOX,
    secret_key="",   # unused for ConnectIPS
    config=config,
)
```

Initiate to get the hidden form fields:

```python
from nepali_payment.models.connectips import PaymentRequest

request = PaymentRequest(
    order_id="order-123",
    amount=12500,               # NPR
    description="Order 123",
)
result = manager.initiate_payment(PaymentResult, request)
if result.success:
    form = result.data.form_fields     # hidden inputs to render
    action = result.data.target_url    # ConnectIPS login form URL
```

Verify on the callback with the query params plus the expected amount:

```python
import json
callback = {
    "TXNID": "order-123",
    "STATUS": "SUCCESS",          # optional; FAILED/CANCELLED short-circuits
    "expectedAmount": 12500,
}
result = manager.verify_payment(PaymentResult, json.dumps(callback))
if result.success:
    trans_ref_id = result.data.trans_ref_id
```

> `cryptography` installs automatically. The cert is loaded inside the service
> and never logged.

## Verify a payment

Same call everywhere, only the argument differs:

```python
# Khalti: pass the pidx
result = manager.verify_payment(PaymentResult, pidx)

# Fonepay: JSON string with prn + merchant credentials
import json
payload = json.dumps({
    "prn": "order-123",
    "merchantCode": "NBQM",
    "username": "merchant-user",
    "password": "merchant-password",
})
result = manager.verify_payment(PaymentResult, payload)

# eSewa: base64 response echoed back from the payment form
result = manager.verify_payment(PaymentResult, base64_response)
```

## Errors

Two kinds, kept separate:

**1. Gateway failures return a failed `PaymentResult`**: no exception, so
rejections, non-2xx responses and network hiccups are data:

```python
result = manager.initiate_payment(PaymentResult, request)
if result.success:
    ...            # proceed with checkout
else:
    logger.warning("Payment failed: %s", result.message)  # no secrets logged
```

Prefer raising? Chain `raise_for_status()`:

```python
result = manager.initiate_payment(PaymentResult, request).raise_for_status()
# this line only runs if the payment actually started
```

> **eSewa is the exception:** it raises `PaymentError` instead of returning a
> failed result, matching eSewa's own API. Catch it when working with eSewa.

**2. Developer mistakes raise typed exceptions.** An empty secret, an
unsupported gateway, a `None`/empty/invalid request, these fail loudly:

```python
from nepali_payment.exceptions import (
    PaymentError, ValidationError, AuthenticationError,
    NetworkError, ProviderError, UnsupportedGatewayError,
)
```

Rule of thumb: if a real payment could fail and you should check `success`, it
comes back as a `PaymentResult`; if it's a bug in your call, it raises.

## Handling callbacks safely

- **Verify server-side, don't trust the query string.** The `pidx` (Khalti) or
  `data` (eSewa) is only an identifier; always round-trip through
  `manager.verify_payment`. For ConnectIPS, pass the params *and* the expected
  amount.
- **Reconcile the amount** against your order before marking paid: Khalti/eSewa
  report it in `result.data.total_amount`, ConnectIPS in
  `result.data.txn_amount`. The `examples/` app stores a wrong-amount settlement
  as `failed`, never `paid`.
- **Keep the handler idempotent.** Providers may redeliver; a user may refresh.
  Re-verifying the same order should be a no-op.
- **Check the order belongs to your user.** If callbacks are `@csrf_exempt`,
  still bind the order to the request/session before releasing goods.

## Fonepay QR status monitoring

Settlement is async, so poll for it with plain **HTTP polling**, shared-hosting
safe:

```python
from datetime import timedelta
from nepali_payment import FonepayPaymentMonitor, PaymentCredentials

monitor = FonepayPaymentMonitor(
    timeout=timedelta(minutes=15),  # overall session lifetime
    interval=timedelta(seconds=5),  # delay between polls
)

@monitor.on("status")               # every poll
def on_status(args):
    print("status:", args.prn, args.payment_status)

@monitor.on("verified")             # settled
def on_verified(args):
    print("verified:", args.prn, args.success)
    monitor.stop(args.prn)

@monitor.on("timeout")
def on_timeout(args):
    print("timeout:", args.prn)

@monitor.on("error")
def on_error(args):
    print("error:", args.prn, args.error_message)

monitor.start("order-123", PaymentCredentials(
    secret_key="...", merchant_code="NBQM",
    username="u", password="p", sandbox_mode=True,
))
```

Session management:

```python
monitor.is_monitoring("order-123")  # is a poller active?
monitor.stop("order-123")           # stop one
monitor.dispose()                   # stop all, release session
```

> **In Django, don't `sleep()` in the request path.** Start the monitor in a
> background task (Celery), a management command, or a task runner so the HTTP
> response returns immediately.

### Why polling, not WebSockets?

Shared hosting forbids persistent connections, daemons and async loops. The
monitoring thread needs none of these; it is plain HTTPS on the shared
`requests.Session`. Dependency-light, synchronous, deploys cleanly.

## See it in action

A runnable Django app in [`examples/`](examples/) wires every gateway into real
views, an `Order` model, provider callbacks and a Fonepay background monitor:

```bash
cd examples
uv sync
cp .env.sample .env
uv run python manage.py makemigrations payments
uv run python manage.py migrate
uv run python manage.py runserver        # open http://127.0.0.1:8000/
uv run python manage.py monitor_fonepay  # poll settlements in a worker
```

Defaults to sandbox; credentials come from env vars. See
[`examples/README.md`](examples/README.md) for the full walkthrough.

## Development

Tooling via [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev                          # venv + dev deps
uv run ruff check nepali_payment tests examples/payments   # lint
uv run ruff format --check nepali_payment tests examples/payments
uv run pytest                                 # tests (~97% coverage with --cov)
NEPALI_PAYMENT_ESEWA_SECRET=... ... uv run pytest tests/test_live_api.py -v
```

## CI

Workflows in `.github/workflows/`:

- **`ci.yml`**: lint, format, Python × Django test matrix (80% coverage gate),
  package build, on push/PR.
- **`live-api.yml`**: real sandbox smoke tests; manual or scheduled; skipped
  unless provider secrets are set.
- **`release.yml`**: builds and publishes to PyPI on `django-nepali-payment/v*`
  tags.

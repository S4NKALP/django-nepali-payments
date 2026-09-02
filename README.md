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
  <img src="https://img.shields.io/badge/Django-4.2%20%7C%205.0-092E20" alt="Django">
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

Accept payments in Nepal from your Django app with a single, consistent API.

We handle **Khalti**, **eSewa**, **Fonepay** (Dynamic QR, Static QR, status
verification, tax refund) and **ConnectIPS**, so you don't have to learn four
different HTTP APIs, four different signing schemes, and four different
callback formats. You get one `PaymentManager`, one `PaymentResult`, done.

The library is deliberately lightweight. No WebSockets, no async event loops,
no background daemons. Just plain HTTPS requests through a pooled
`requests.Session`, which is why it runs happily even on shared hosting.

```bash
pip install django-nepali-payment
# or with uv
uv add django-nepali-payment
```

**Requirements:** Python 3.11+, Django 4.2+ (the library itself is not tied to a
specific Django major). It bundles `requests` for transport and `cryptography`
for ConnectIPS RSA signing.

## What you get

- **One shape for every gateway.** Every call returns a `PaymentResult`, so
  reading a success, a failure, or some provider data looks the same whether it
  came from Khalti or Fonepay.
- **Signatures that just work.** We reproduced the exact signing from each
  provider's reference implementation, so you don't have to debug hex vs base64
  yourself:
  - eSewa: HMAC-SHA256 (base64)
  - Fonepay: HMAC-SHA512 (lowercase hex)
  - Khalti: `Authorization: key <secret>` header
  - ConnectIPS: SHA256withRSA over your merchant certificate
- **One flag for sandbox vs production.** Flip `PaymentMode` and you're done.
- **Shared-hosting-safe Fonepay monitoring.** Settlement is checked with a
  lightweight polling thread rather than a WebSocket, so it works where long
  connections are forbidden.
- **Fonepay extras built in.** Tax refunds and Static QR out of the box.
- **Connection reuse.** One `requests.Session` is shared across calls, with
  sensible timeouts.
- **Optional retries.** `ApiService` can retry transient failures (connection
  drops and HTTP 429/5xx) with exponential backoff — opt in per client.

---

## How it's built

The library has three small layers, all of which you can use directly:

- **`PaymentManager`** — the entry point. Pick a gateway, mode and secret key
  once, then call `initiate_payment` / `verify_payment` (plus Fonepay tax refund
  and static QR) without thinking about which provider you chose.
- **Gateway services** — one per provider (Khalti, eSewa, Fonepay, ConnectIPS).
  Every service extends `BasePaymentService`, which stores the things all
  gateways share (the HTTP client, the sandbox-vs-production base URL, and a
  "turn any error into a failed result" helper). Each service only implements
  its own initiate/verify logic and signing.
- **Request/response models** — `PaymentResult` is the universal answer type.
  Each gateway also has typed request models. The request models use Python
  `dataclass(slots=True)` and serialize themselves with `dataclasses.asdict`,
  so they are small in memory and safe to pass straight to a provider.

Under the hood everything is synchronous HTTPS through a pooled
`requests.Session` — no event loops, WebSockets or daemons.

---

## Quick start

Create a manager once for your gateway and mode, then reuse it:

```python
from nepali_payment import PaymentManager, PaymentMethod, PaymentMode, PaymentResult

manager = PaymentManager(
    payment_method=PaymentMethod.ESEWA,   # or KHALTI, FONEPAY
    payment_mode=PaymentMode.SANDBOX,     # switch to PRODUCTION when ready
    secret_key="your-secret-key",
)
```

Every call returns the same `PaymentResult`, with these attributes:

| Field        | What it holds                                    |
| ------------ | ------------------------------------------------ |
| `success`    | Did the operation succeed?                       |
| `message`    | Human-readable message (no secrets are logged)   |
| `data`       | Gateway-specific response object (may be `None`) |
| `status`     | Reserved; currently unused (always `200`)        |
| `error_code` | Reserved; currently unused (always `None`)       |

`PaymentResult` also behaves like a `bool` inside an `if`, and exposes
`raise_for_status()` to turn a failure into a raised `PaymentError` when you'd
rather not handle it inline:

```python
result = manager.initiate_payment(PaymentResult, request).raise_for_status()
print(result.data)   # only reached if the payment actually started
```

### Tuning the HTTP client

By default the manager creates its own `ApiService` — a pooled
`requests.Session` with a 15s timeout. You can inject your own to change the
timeout, enable retries, or share one session across several managers:

```python
from nepali_payment import PaymentManager, PaymentMethod, PaymentMode
from nepali_payment.http import ApiService

api = ApiService(
    timeout=30.0,        # default request timeout (seconds)
    retries=2,           # retry transient failures 0..N times (default 0)
    retry_backoff=1.0,   # initial backoff seconds; doubles each attempt
)

manager = PaymentManager(
    PaymentMethod.KHALTI,
    PaymentMode.SANDBOX,
    secret_key="your-secret-key",
    api=api,
)
```

The `ApiService` is shared and reuse-cached, so many calls never open a new
connection. Call `api.close()` (or `manager._api_service().close()`) to release
pooled connections when your app shuts down.

> Retries are off by default because re-sending a *payment initiation* could
> double-charge. Enable them only for endpoints that are safe to repeat.

---

## Initiate a payment

Each gateway has its own request model, but the call is always
`manager.initiate_payment(PaymentResult, request)`.

### eSewa

```python
from nepali_payment.models.esewa import PaymentRequest as EsewaRequest

request = EsewaRequest(
    amount="100",
    total_amount="113",          # amount + tax + charges
    transaction_uuid="order-123",
    product_code="EPAYTEST",     # your eSewa product code
    signed_field_names="total_amount,transaction_uuid,product_code",
)

result = manager.initiate_payment(PaymentResult, request)
if result.success:
    redirect_url = result.data.payment_url   # send the customer here
```

eSewa redirects the customer to a hosted payment form.

### Khalti

```python
from nepali_payment.models.khalti import PaymentRequest as KhaltiRequest

request = KhaltiRequest(
    return_url="https://yoursite.com/callback",
    website_url="https://yoursite.com",
    amount=1000,                       # in paisa (NPR 10.00)
    purchase_order_id="order-123",
    purchase_order_name="My Order",
)

result = manager.initiate_payment(PaymentResult, request)
if result.success:
    redirect_url = result.data.payment_url   # send the customer here
    pidx = result.data.pidx                  # keep for verification later
```

> Khalti amounts are in **paisa** (1 NPR = 100 paisa).

### Fonepay (Dynamic QR)

```python
from nepali_payment.models.fonepay import QrRequest

request = QrRequest(
    amount="100",
    remarks1="Order 123",
    remarks2="Main",
    prn="order-123",
    merchant_code="NBQM",
    username="merchant-user",
    password="merchant-password",
)

result = manager.initiate_payment(PaymentResult, request)
if result.success:
    qr_data = result.data.qr_message   # show this to the customer
```

The dynamic QR bakes the amount into the QR. Fonepay settlement happens
asynchronously, so you'll usually pair this with the [status monitor](#fonepay-qr-status-monitoring).

---

## Fonepay Static QR

A static QR is a single, fixed merchant QR (think: printed at a point of sale).
The customer types in the amount when they scan, so you don't need an amount up
front. Fetch the QR payload once per station and render it:

```python
from nepali_payment.models.fonepay import StaticQrRequest

request = StaticQrRequest(
    prn="merchant-station",
    merchant_code="NBQM",
    username="merchant-user",
    password="merchant-password",
)

result = manager.process_static_qr(PaymentResult, request)
if result.success:
    static_qr = result.data.qr_message   # render/print this once for this station
```

> `process_static_qr` is Fonepay-only, just like the tax refund. Calling it on
> another gateway raises `ValidationError`. For settlement checks, use
> `verify_payment` or the `FonepayPaymentMonitor` with the payment's PRN.

---

## ConnectIPS

ConnectIPS is a **form POST** gateway. You render a hidden form and hand the
customer over to ConnectIPS, who redirects them back once the payment is done.
It signs with **SHA256withRSA** using a merchant certificate (a `.pfx`, `.p12`
or `.pem` key), so instead of a secret key the manager takes a config object:

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
    payment_mode=PaymentMode.SANDBOX,     # switch to PRODUCTION when ready
    secret_key="",                        # unused for ConnectIPS
    config=config,
)
```

Initiate the payment. You get back the hidden form fields to render, plus the
URL to POST them to:

```python
from nepali_payment.models.connectips import PaymentRequest

request = PaymentRequest(
    order_id="order-123",
    amount=12500,               # NPR amount
    description="Order 123",
)
result = manager.initiate_payment(PaymentResult, request)
if result.success:
    form = result.data.form_fields     # hidden inputs to render
    action = result.data.target_url    # the ConnectIPS login form URL
```

When ConnectIPS redirects back to your callback, verify using the query
parameters it sent (plus the amount you expected):

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

> ConnectIPS needs the `cryptography` package, which is installed automatically
> with the library. The certificate is loaded inside the service and never
> logged.

---

## Verify a payment

The verification call is also the same across gateways — only the argument
differs:

```python
# Khalti: pass the pidx
result = manager.verify_payment(PaymentResult, pidx)

# Fonepay: pass a JSON string with prn + merchant credentials
import json
payload = json.dumps({
    "prn": "order-123",
    "merchantCode": "NBQM",
    "username": "merchant-user",
    "password": "merchant-password",
})
result = manager.verify_payment(PaymentResult, payload)

# eSewa: pass the base64 response echoed back from the payment form
result = manager.verify_payment(PaymentResult, base64_response)
```

---

## Errors

There are two kinds of failures, and the library keeps them separate:

**1. Gateway failures return a failed `PaymentResult`** — no exception is
raised, so you can treat rejections, non-2xx responses and network hiccups as
data:

```python
result = manager.initiate_payment(PaymentResult, request)

if result.success:
    # proceed with checkout
    ...
else:
    logger.warning("Payment failed: %s", result.message)  # no secrets logged
```

If you'd rather stop and handle it with a raised error, chain
`raise_for_status()`:

```python
result = manager.initiate_payment(PaymentResult, request).raise_for_status()
# this line only runs if the payment actually started
```

> eSewa is the one exception to "failures don't raise": it raises `PaymentError`
> instead of returning a failed result, matching how eSewa's own API reports
> errors. Catch it (or catch `PaymentError`) when working with eSewa directly.

**2. Developer-facing mistakes raise typed exceptions.** An empty secret, an
unsupported gateway, a `None`/empty/invalid request — these are bugs in your
call, so they fail loudly:

```python
from nepali_payment.exceptions import (
    PaymentError, ValidationError, AuthenticationError,
    NetworkError, ProviderError, UnsupportedGatewayError,
)
```

The rule of thumb: if a real payment could fail and you should check `success`,
it comes back as a `PaymentResult`; if it's a mistake in your code, it raises.

---

## Handling callbacks safely

When Khalti, eSewa or ConnectIPS redirects the customer back to your site, you
verify the payment before marking it complete. A few practical rules:

- **Verify server-side, don't trust the query string.** The `pidx` (Khalti) or
  `data` (eSewa) in the URL is only an identifier — always round-trip it through
  `manager.verify_payment`, never assume it means "paid". For ConnectIPS, pass
  the callback parameters *and* the amount you expected.
- **Reconcile the amount.** Confirm the verified amount matches your order's
  amount before marking it paid. Khalti and eSewa report the paid amount in
  `result.data.total_amount`, ConnectIPS in `result.data.txn_amount`. The
  `examples/` app does exactly this — a settled payment for the wrong amount is
  stored as `failed`, never `paid`.
- **Keep the callback handler idempotent.** A provider may redeliver a callback,
  or a user may refresh. Guard your handler so re-verifying the same order is a
  no-op rather than a duplicate charge or state flip.
- **Check the order belongs to your user.** If callbacks are unauthenticated
  (`@csrf_exempt`), binding the order to the current request/session still
  matters in real apps before you release goods.

---

## Fonepay QR status monitoring

Fonepay's QR flow is asynchronous. The customer scans, pays, and you need to
find out _when_ it settles. Here it's plain **HTTP polling** so it works on shared hosting.

Attach a few handlers and start a poller per payment:

```python
from datetime import timedelta
from nepali_payment import FonepayPaymentMonitor, PaymentCredentials

monitor = FonepayPaymentMonitor(    # defaults shown; tweak as you like
    timeout=timedelta(minutes=15),  # overall session lifetime
    interval=timedelta(seconds=5),  # delay between polls
)

@monitor.on("status")               # fires on every poll
def on_status(args):
    print("status:", args.prn, args.payment_status)

@monitor.on("verified")             # payment settled
def on_verified(args):
    print("verified:", args.prn, args.success)
    monitor.stop(args.prn)          # done with this one

@monitor.on("timeout")              # no terminal state in time
def on_timeout(args):
    print("timeout:", args.prn)

@monitor.on("error")                # poller/network error
def on_error(args):
    print("error:", args.prn, args.error_message)

monitor.start(
    "order-123",
    PaymentCredentials(
        secret_key="...",
        merchant_code="NBQM",
        username="u",
        password="p",
        sandbox_mode=True,
    ),
)
```

You can also manage sessions directly:

```python
monitor.is_monitoring("order-123")  # is a poller active?
monitor.stop("order-123")           # stop one poller
monitor.dispose()                   # stop all and release the session
```

> **In Django, don't `sleep()` in the request path.** Start the monitor in a
> background task (Celery), a management command, or your task runner so the
> HTTP response returns immediately.

---

## Why polling instead of WebSockets?

Shared hosting usually forbids persistent connections, daemon processes and
async event loops. The polling monitor needs none of those. It just issues
plain HTTPS requests on a background thread through the shared
`requests.Session`. The result is a library that's dependency-light,
synchronous, and deploys cleanly on shared hosting and typical Django setups
alike.

---

## See it in action

There's a complete, runnable Django project in [`examples/`](examples/). It
wires every gateway into real views, an `Order` model, provider callbacks and a
Fonepay background monitor — the way you'd actually use the library for real:

```bash
cd examples
uv sync
cp .env.sample .env
uv run python manage.py makemigrations payments
uv run python manage.py migrate
uv run python manage.py runserver        # open http://127.0.0.1:8000/
uv run python manage.py monitor_fonepay  # poll Fonepay settlements in a worker
```

See [`examples/README.md`](examples/README.md) for the full walkthrough. It
defaults to sandbox mode and reads credentials from environment variables, so
you can poke around the UI and the request/response shapes safely before going
live.

---

## Development

We use [uv](https://docs.astral.sh/uv/) for the environment and tooling:

```bash
# install the package and dev deps in a venv
uv sync --extra dev

# lint (library, tests and the example app)
uv run ruff check nepali_payment tests examples/payments

# format
uv run ruff format --check nepali_payment tests examples/payments

# run all tests (live sandbox tests are skipped without credentials)
uv run pytest

# run tests with a coverage report (the suite sits around 97%)
uv run pytest --cov=nepali_payment

# live sandbox smoke tests (hits real provider endpoints)
NEPALI_PAYMENT_ESEWA_SECRET=... \
NEPALI_PAYMENT_KHALTI_SECRET=... \
NEPALI_PAYMENT_FONEPAY_SECRET=... NEPALI_PAYMENT_FONEPAY_MERCHANT=... \
NEPALI_PAYMENT_FONEPAY_USERNAME=... NEPALI_PAYMENT_FONEPAY_PASSWORD=... \
uv run pytest tests/test_live_api.py -v
```

## CI

GitHub Actions workflows live in `.github/workflows/`:

- **`ci.yml`** lints, formats, and runs a Python × Django test matrix with an
  80% coverage gate, plus a package build check, on every push/PR.
- **`live-api.yml`** runs real sandbox smoke tests, either manually or on a
  schedule; skipped unless provider credentials are configured as repo secrets.
- **`release.yml`** builds and publishes to PyPI on `django-nepali-payment/v*`
  tags.

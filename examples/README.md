# Django example project

A ready-to-run **Django** application demonstrating how to integrate every
gateway in `django-nepali-payment` the way you would in a real project, through
views, models, URL callbacks and a management command, rather than as
standalone scripts.

| Component                                         | Purpose                                                                                                           |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `manage.py` / `example_project/`                  | A minimal Django project (settings, urls, wsgi/asgi).                                                             |
| `payments/models.py`                              | An `Order` model storing the payment lifecycle (status, provider ref, raw payload).                               |
| `payments/views.py`                      | `create_order` (initiate), `callback` (provider return), `verify_order` (re-check) for Khalti, eSewa, Fonepay and ConnectIPS. |
| `payments/urls.py`                       | Routed pages for creating payments and receiving provider callbacks.                                                          |
| `payments/management/commands/monitor_fonepay.py` | Background worker that polls Fonepay for settlements (shared-hosting safe).                                        |
| `.env.sample`                            | Credential template, copy to `.env` and fill in your keys.                                                                    |

## Run it

From this directory, using [uv](https://docs.astral.sh/uv/):

```bash
# create the venv and install the library + example deps
uv sync

# copy the credential template and fill in your keys
cp .env.sample .env

# create migrations from the Order model and set up the database
uv run python manage.py makemigrations payments
uv run python manage.py migrate

# run the dev server
uv run python manage.py runserver
```

Migrations for the example `payments` app are generated on the fly (they're not
committed to the repo), so run `makemigrations` the first time to create the
`Order` table.

Open <http://127.0.0.1:8000/> to see the home page and start payments.

## How the flow works per gateway

All follow the same pattern in `views.py`:

1. `create_order` builds the gateway request and calls
   `PaymentManager.initiate_payment(...)`.
2. **Khalti / eSewa** the customer is redirected to
   `result.data.payment_url` (the provider's hosted page).
   - Khalti calls back with `?pidx=` to `/callback/khalti/`.
   - eSewa calls back with a base64 `?data=` to `/callback/esewa/`.
3. **Fonepay** `result.data.qr_message` is shown for scanning; settlement is
   watched by the background monitor (below).
4. **ConnectIPS** `result.data.form_fields` is rendered as a hidden form that
   posts to `result.data.target_url` (the bank's sign-in page). The demo ships a
   simulated multi-step checkout (login → select bank → confirm) that reports
   back to `/callback/connectips/` the same way a real session would.

The `Order` row is updated as the payment moves through `pending` -> `initiated`
-> `paid` / `failed` / `timeout`.

**Which order you can "Verify" after the fact:** Khalti re-checks
server-side by `pidx`, and Fonepay is polled by the background monitor. eSewa
and ConnectIPS do not expose a status lookup by transaction id, so the demo only
updates them from their callback payload — the "Verify" button on the orders
table explains this rather than calling the API blindly.

## Monitor a Fonepay payment

Start the polling worker in a terminal:

```bash
uv run python manage.py monitor_fonepay
```

It scans for `fonepay` orders still in `initiated` state, starts
`FonepayPaymentMonitor` for each PRN, and updates orders to `paid` / `failed` /
`timeout` when the settlement events fire. This runs on a plain background
thread, no WebSocket, no daemon, nothing that breaks on shared hosting.

## Going live

Set these environment variables in `.env` before starting the server:

```bash
export PAID_MODE=production
export PAID_BASE_URL=...            # public HTTPS base for callback URLs
export ESEWA_SECRET=...
export ESEWA_PRODUCT_CODE=...
export KHALTI_SECRET=...
export FONEPAY_SECRET=...
export FONEPAY_MERCHANT=...
export FONEPAY_USERNAME=...
export FONEPAY_PASSWORD=...
# optional monitor tuning (seconds); defaults shown
export FONEPAY_MONITOR_TIMEOUT=900
export FONEPAY_MONITOR_INTERVAL=5
export CONNECTIPS_MERCHANT_ID=...
export CONNECTIPS_APP_ID=...
export CONNECTIPS_APP_NAME=...
export CONNECTIPS_APP_PASSWORD=...
export CONNECTIPS_CERT_PATH=...       # .pfx / .p12 / .pem
export CONNECTIPS_CERT_PASSWORD=...
export CONNECTIPS_DEMO_USER=...
export CONNECTIPS_DEMO_PASSWORD=...
export CONNECTIPS_DEMO_CAPTCHA=...
export CONNECTIPS_DEMO_TPIN=...
export CONNECTIPS_DEMO_OTP=...
```

When `PAID_BASE_URL` is empty the demo derives callback URLs from the incoming
request host, which works locally but is unreliable behind a proxy or on a real
domain — set it to a public HTTPS base before going live.

Without them the example app runs in **sandbox** mode with placeholder keys so
you can explore the UI and the request/response shapes safely. ConnectIPS runs a
**simulated** checkout when `CONNECTIPS_MERCHANT_ID` is empty.

### Working test credentials

The default `.env.sample` ships with test keys that are actually accepted today:

| Gateway  | Test credentials                                                            |
| -------- | --------------------------------------------------------------------------- |
| Khalti   | Mobile `9800000001/2/3/4/5`, Pin `1111`, OTP `987654`, secret `live_secret_key_68791341fdd94846a146f0457ff7b455` |
| eSewa    | Username `9806800001/2/3/4/5`, Password `Nepal@123`, Token `123456`, secret `8gBm/:&EnhH.1/q`, product code `EPAYTEST` |
| Fonepay  | See note below — no public sandbox credentials exist                       |

### Fonepay sandbox caveat

Fonepay's **sandbox** API endpoint (`dev-merchantapi.fonepay.com`) currently
serves an **expired TLS certificate**, so any request to it fails with
`SSLCertVerificationError`. This is on Fonepay's side, not the library's.

The demo targets the **production** endpoint instead (via `PAID_MODE=production`
for Fonepay) and clearly warns that it performs **real transactions**. Fonepay
has not published shared test credentials, so you need your own merchant
account to exercise the QR/status flows.

## Real-host callback caveat

`success_url` / `return_url` are built from the incoming request's host, so when
running on a LAN or a real domain point your provider dashboard (and
`ALLOWED_HOSTS` in `example_project/settings.py`) at the reachable public URL.

## Note on the example server

This project exists to demonstrate the library's API, it uses the Django
development server and SQLite. For production, run behind a real WSGI server
(e.g. Gunicorn/uWSGI), confirm all callbacks hit HTTPS endpoints, and mark
`PAID_MODE=production` only when you are truly live.

"""Django views demonstrating Khalti, eSewa, Fonepay and ConnectIPS.

Each gateway follows the same shape:

    initiate -> redirect the customer to the provider (Khalti/eSewa) or show
    them a QR (Fonepay) or a hosted form (ConnectIPS); then verify after the
    provider calls back (Khalti/eSewa/ConnectIPS) or after the background
    monitor reports settlement (Fonepay).

Where a gateway's sandbox/credentials are unavailable the views fall back to a
simulated flow so the demo still shows realistic behaviour.
"""

import json
import threading
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from nepali_payment.enums import PaymentMethod, PaymentMode
from nepali_payment.exceptions import AuthenticationError, NetworkError, PaymentError, ValidationError
from nepali_payment.helpers import load_rsa_private_key
from nepali_payment.manager import PaymentManager
from nepali_payment.models import PaymentResult
from nepali_payment.models.connectips import PaymentRequest as ConnectIpsPaymentRequest
from nepali_payment.models.esewa import PaymentRequest as EsewaRequest
from nepali_payment.models.fonepay import QrRequest, StaticQrRequest
from nepali_payment.models.khalti import PaymentRequest as KhaltiRequest
from nepali_payment.services.connectips import ConnectIpsConfig

from .models import Order

PAYMENT_MODE = PaymentMode.PRODUCTION if settings.PAID_MODE.lower() == "production" else PaymentMode.SANDBOX
MODE_LABEL = PAYMENT_MODE.value.lower()

GATEWAYS = {
    "khalti": {
        "method": PaymentMethod.KHALTI,
        "secret": settings.KHALTI_SECRET,
    },
    "esewa": {
        "method": PaymentMethod.ESEWA,
        "secret": settings.ESEWA_SECRET,
    },
    "fonepay": {
        "method": PaymentMethod.FONEPAY,
        "secret": settings.FONEPAY_SECRET,
    },
    "connectips": {
        "method": PaymentMethod.CONNECTIPS,
        "secret": "",
    },
}

#: Reuse one PaymentManager (and its pooled requests.Session) per gateway so a
#: request handler that initiates+verifies in a loop does not open a fresh TCP
#: connection for every call.
_MANAGERS: dict[str, PaymentManager] = {}

#: ConnectIPS config is request-dependent (it carries per-request callback URLs),
#: so its PaymentManager cannot be cached wholesale like the other gateways.
#: Parsing the RSA certificate, however, is expensive and request-independent, so
#: it is done once and reused across every ConnectIPS manager via ``_private_key``.
_CI_PRIVATE_KEY = None
_CI_PRIVATE_KEY_LOCK = threading.Lock()


def _connectips_config(request=None) -> ConnectIpsConfig:
    """Build a ConnectIPS config from the environment settings.

    The merchant certificate is parsed once and reused (via ``config._private_key``)
    so every new ConnectIPS manager does not re-parse the PFX per request.
    """
    success_url = _abs(request, "payments:payments-callback", gateway="connectips") if request is not None else None
    failure_url = _abs(request, "payments:payments-failure", gateway="connectips") if request is not None else None
    config = ConnectIpsConfig(
        merchant_id=settings.CONNECTIPS_MERCHANT_ID,
        app_id=settings.CONNECTIPS_APP_ID,
        app_name=settings.CONNECTIPS_APP_NAME,
        app_password=settings.CONNECTIPS_APP_PASSWORD,
        cert_path=settings.CONNECTIPS_CERT_PATH or None,
        cert_password=settings.CONNECTIPS_CERT_PASSWORD or None,
        success_url=success_url,
        failure_url=failure_url,
    )

    # Reuse the parsed RSA private key across every ConnectIPS manager. Parse it
    # lazily the first time it is actually needed (i.e. a cert is configured) and
    # hold it in a module-level cache guarded by a lock for thread safety.
    if config.cert_path or config.cert_data:
        global _CI_PRIVATE_KEY
        if _CI_PRIVATE_KEY is None:
            with _CI_PRIVATE_KEY_LOCK:
                if _CI_PRIVATE_KEY is None:
                    _CI_PRIVATE_KEY = load_rsa_private_key(
                        cert_path=config.cert_path,
                        cert_password=config.cert_password,
                    )
        config._private_key = _CI_PRIVATE_KEY

    return config


def _build_manager(gateway: str, request=None) -> PaymentManager:
    """Build a PaymentManager for a gateway from the shared configuration.

    Manager instances are cached per gateway, so the pooled HTTP session is
    reused across operations. ConnectIPS cannot be cached wholesale (its config
    carries per-request callback URLs), but its RSA certificate is parsed once
    and shared, so each new manager still avoids re-parsing the PFX.
    """
    conf = GATEWAYS[gateway]
    if gateway != "connectips":
        cached = _MANAGERS.get(gateway)
        if cached is not None:
            return cached
        manager = PaymentManager(
            payment_method=conf["method"],
            payment_mode=PAYMENT_MODE,
            secret_key=conf["secret"],
        )
        _MANAGERS[gateway] = manager
        return manager

    config = _connectips_config(request)
    return PaymentManager(
        payment_method=conf["method"],
        payment_mode=PAYMENT_MODE,
        secret_key=conf["secret"],
        config=config,
    )


def _abs(request, name: str, **kwargs) -> str:
    """Build an absolute provider-callback URL for a named route."""
    path = reverse(name, kwargs=kwargs)
    base = getattr(settings, "PAYMENT_BASE_URL", "") or request.build_absolute_uri("/")
    if not base.endswith("/"):
        base += "/"
    return base.rstrip("/") + path


def home(request) -> HttpResponse:
    """List gateways and your payment options."""
    return render(
        request,
        "home.html",
        {"gateways": list(GATEWAYS), "mode": MODE_LABEL},
    )


@require_http_methods(["GET", "POST"])
def create_order(request, gateway: str) -> HttpResponse:
    """Create an Order and initiate a payment on the chosen gateway."""
    if gateway not in GATEWAYS:
        raise ValueError(f"Unknown gateway: {gateway}")

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    is_json = is_ajax and "application/json" in request.content_type

    if request.method == "GET":
        return render(request, "create.html", {"gateway": gateway, "mode": MODE_LABEL})

    # Parse form or JSON body
    if is_json:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            body = {}
        amount = str(body.get("amount", "1.00"))
        description = body.get("remarks1", "").strip() or body.get("description", "").strip()
    else:
        amount = request.POST.get("amount", "10.00")
        description = request.POST.get("description", "").strip()

    try:
        order = Order.objects.create(
            gateway=gateway,
            order_id=f"{gateway}-{uuid.uuid4().hex[:10]}",
            amount=amount,
            description=description,
        )
    except Exception as exc:  # noqa: BLE001  # surface bad user input
        return _create_error(request, gateway, is_ajax, f"Could not create order: {exc}")

    try:
        payload = _initiate(gateway, order, request)
    except ValidationError as exc:
        order.delete()
        return _create_error(request, gateway, is_ajax, f"Invalid payment request: {exc}")
    except (NetworkError, AuthenticationError, PaymentError) as exc:
        order.delete()
        return _create_error(request, gateway, is_ajax, f"{gateway} returned an error: {exc}")

    # Fonepay AJAX: return QR data as JSON
    if gateway == "fonepay" and is_ajax:
        return JsonResponse(
            {"qr_message": payload.qr_message, "prn": order.order_id, "simulated": getattr(payload, "simulated", False)}
        )

    # ConnectIPS returns a hidden form to POST to the gateway login page.
    if gateway == "connectips":
        return render(
            request,
            "redirect_form.html",
            {
                "gateway": gateway,
                "order": order,
                "target_url": payload.target_url,
                "form_fields": payload.form_fields,
                "simulated": getattr(payload, "simulated", False),
            },
        )

    # Khalti/eSewa redirect to the provider; Fonepay shows a QR to scan.
    if gateway == "fonepay":
        return render(
            request,
            "initiated.html",
            {"gateway": gateway, "order": order, "qr_message": payload.qr_message},
        )
    return HttpResponseRedirect(payload.payment_url)


def _create_error(request, gateway: str, is_ajax: bool, message: str) -> HttpResponse:
    """Return a create-order error as JSON (AJAX) or as an inline form render."""
    if is_ajax:
        return JsonResponse({"error": message}, status=400)
    messages.error(request, message)
    return render(request, "create.html", {"gateway": gateway, "mode": MODE_LABEL})


@require_http_methods(["GET", "POST"])
def static_qr(request) -> HttpResponse:
    """Return Fonepay's reusable static QR payload (no amount; the customer
    enters the amount at scan time).

    Unlike the dynamic per-transaction QR, the static QR is a single fixed
    merchant QR. It is fetched via the library's ``process_static_qr``.
    """
    if PAYMENT_MODE == PaymentMode.SANDBOX:
        # Sandbox API is down (expired TLS cert): fall back to a simulated QR.
        sim = _simulate_fonepay_qr({"prn": settings.FONEPAY_MERCHANT, "remarks1": "Static merchant QR"})
        return JsonResponse({"qr_message": sim.data.qr_message, "static": True, "simulated": True})

    manager = _build_manager("fonepay", request)
    try:
        req = StaticQrRequest(
            prn=settings.FONEPAY_MERCHANT,
            merchant_code=settings.FONEPAY_MERCHANT,
            username=settings.FONEPAY_USERNAME,
            password=settings.FONEPAY_PASSWORD,
        )
        result = manager.process_static_qr(PaymentResult, req)
    except (NetworkError, AuthenticationError, PaymentError, ValidationError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    _raise_if_failed(result, "fonepay")
    return JsonResponse({"qr_message": result.data.qr_message, "static": True})


def _simulate_fonepay_qr(fields: dict) -> SimpleNamespace:
    """Build a stand-in Fonepay QR payload for the demo.

    Fonepay's sandbox (dev-merchantapi.fonepay.com) serves an expired TLS
    certificate, so real QR generation cannot run in sandbox mode. Rather than
    showing an error, this returns a representative QR payload flagged
    ``simulated`` so the demo still renders a scannable-looking QR. It does NOT
    represent a real Fonepay transaction.
    """
    payload = {
        "amount": fields.get("amount") or "",
        "prn": fields.get("prn") or settings.FONEPAY_MERCHANT,
        "merchantCode": settings.FONEPAY_MERCHANT,
        "merchantName": "Fonepay Demo Merchant",
        "currency": "NPR",
        "remarks1": fields.get("remarks1") or "",
        "simulated": True,
    }
    # Mirrors PaymentResult shape so callers can treat it identically.
    return SimpleNamespace(data=SimpleNamespace(qr_message=json.dumps(payload), simulated=True))


def _simulate_connectips(order: Order, request) -> SimpleNamespace:
    """Build a stand-in ConnectIPS form for the demo.

    ConnectIPS needs an RSA certificate plus merchant credentials that are
    not available in the default demo. When unconfigured, this returns a
    representative form payload mirroring the real ``FormResponse`` so the
    demo still renders the ConnectIPS POST-to-login flow. It does NOT
    represent a real ConnectIPS transaction.
    """
    txn_date = datetime.now(UTC).strftime("%d-%m-%Y")
    form_fields = {
        "MERCHANTID": settings.CONNECTIPS_MERCHANT_ID or "DEMO",
        "APPID": settings.CONNECTIPS_APP_ID or "DEMO",
        "APPNAME": settings.CONNECTIPS_APP_NAME or "Fonepay Demo",
        "TXNID": order.order_id,
        "TXNDATE": txn_date,
        "TXNCRNCY": "NPR",
        "TXNAMT": str(round(float(order.amount))),
        "REFERENCEID": order.order_id,
        "REMARKS": order.description or "",
        "PARTICULARS": order.description or "",
        "TOKEN": "SIMULATED",
        "SUCCESSURL": _abs(request, "payments:payments-callback", gateway="connectips") or "",
        "FAILUREURL": _abs(request, "payments:payments-failure", gateway="connectips") or "",
        "SIMULATED": "True",
    }
    # The simulated form posts to a mock ConnectIPS payment page (instead of
    # a real bank page), which then reports back to our own callback so the
    # callback->verify flow matches how the real gateway reports settlement.
    target_url = _abs(request, "payments:payments-connectips-payment") or "#"
    return SimpleNamespace(data=SimpleNamespace(target_url=target_url, form_fields=form_fields, simulated=True))


def _mock_connectips_result(txnid: str, success: bool) -> PaymentResult:
    """Build a fake ConnectIPS verification result for the simulated callback."""
    data = {
        "reference_id": txnid,
        "status": "SUCCESS" if success else "FAILED",
        "transaction_id": f"SIM{txnid[:12]}",
        "amount": "0",
        "simulated": True,
    }
    return PaymentResult(
        data=SimpleNamespace(**data),
        success=success,
        message="Simulated ConnectIPS payment " + ("succeeded" if success else "failed."),
    )


# A representative slice of NCHL's member BFIs for the "select bank" step.
CONNECTIPS_BANKS = [
    "Nabil Bank",
    "Nepal Investment Bank",
    "Standard Chartered Bank",
    "Himalayan Bank",
    "NIC Asia Bank",
    "Global IME Bank",
    "Prabhu Bank",
    "Machhapuchchhre Bank",
    "Laxmi Bank",
    "Kumari Bank",
    "Siddhartha Bank",
    "Everest Bank",
    "Agriculture Development Bank",
    "Prabhu Financial Institution",
    "Nepal Rastra Bank",
]


def _connectips_demo_credentials() -> list[dict]:
    """Return the demo credentials used to pre-fill the mock ConnectIPS flow."""
    return [
        {"label": "Username", "value": settings.CONNECTIPS_DEMO_USER},
        {"label": "Password", "value": settings.CONNECTIPS_DEMO_PASSWORD},
        {"label": "Captcha", "value": settings.CONNECTIPS_DEMO_CAPTCHA},
        {"label": "Transaction Password (PIN)", "value": settings.CONNECTIPS_DEMO_TPIN},
        {"label": "OTP (sent to registered mobile)", "value": settings.CONNECTIPS_DEMO_OTP},
    ]


@require_http_methods(["GET", "POST"])
@csrf_exempt
def connectips_payment(request) -> HttpResponse:
    """Mock the ConnectIPS checkout as a faithful multi-step flow.

    Real ConnectIPS navigates: login (username/password/captcha) -> select a
    linked bank account -> confirm with the Transaction Password/OTP. This mock
    replicates those steps with demo credentials and, on the final Submit,
    reports back to ``/callback/connectips/`` exactly as a real session would on
    settlement.
    """
    params = dict(request.POST.items()) or {}
    # Step 0: the merchant redirect form posts payment details to start here.
    if params.get("SIMULATED") == "True":
        txnid = params.get("TXNID") or params.get("REFERENCEID") or request.session.get("ci_txnid")
        request.session["ci_txnid"] = txnid
        request.session["ci_stage"] = "login"
        request.session["ci_order_data"] = params

    txnid = request.session.get("ci_txnid")
    order = Order.objects.filter(gateway="connectips", lookup_ref=txnid).first()
    order_data = request.session.get("ci_order_data") or {}
    ctx = {
        "gateway": "connectips",
        "amount": params.get("TXNAMT") or order_data.get("TXNAMT") or (str(order.amount) if order else ""),
        "merchant": order_data.get("APPNAME") or "Demo Merchant",
        "order_id": txnid or "",
        "txn_date": order_data.get("TXNDATE") or "",
        "ref_id": params.get("REFERENCEID") or txnid or "",
        "banks": CONNECTIPS_BANKS,
        "demo_username": settings.CONNECTIPS_DEMO_USER,
        "demo_password": settings.CONNECTIPS_DEMO_PASSWORD,
        "demo_captcha": settings.CONNECTIPS_DEMO_CAPTCHA,
        "demo_credentials": _connectips_demo_credentials(),
        "error": None,
    }

    step = request.POST.get("ci_step")
    if step == "login":
        uname = request.POST.get("ci_username", "")
        pwd = request.POST.get("ci_password", "")
        captcha = request.POST.get("ci_captcha", "").strip()
        if (
            uname != settings.CONNECTIPS_DEMO_USER
            or pwd != settings.CONNECTIPS_DEMO_PASSWORD
            or captcha.upper() != settings.CONNECTIPS_DEMO_CAPTCHA
        ):
            ctx["error"] = "Invalid username, password or captcha. Try the demo credentials shown below."
            return render(request, "connectips_login.html", ctx)
        request.session["ci_stage"] = "bank"
        return _render_ci_banks(request, ctx)
    if step == "bank":
        if not request.POST.get("ci_bank"):
            ctx["error"] = "Please select the bank account to pay from."
            return _render_ci_banks(request, ctx)
        request.session["ci_bank"] = request.POST.get("ci_bank")
        request.session["ci_stage"] = "confirm"
        ctx["bank"] = request.session["ci_bank"]
        return render(request, "connectips_confirm.html", ctx)
    if step == "confirm":
        tp = request.POST.get("ci_tpin", "")
        if tp != settings.CONNECTIPS_DEMO_TPIN and tp != settings.CONNECTIPS_DEMO_OTP:
            ctx["bank"] = request.session.get("ci_bank")
            ctx["error"] = "Invalid Transaction Password / OTP. Try the demo values shown below."
            return render(request, "connectips_confirm.html", ctx)
        request.session["ci_stage"] = "done"
        return render(request, "connectips_processing.html", {"gateway": "connectips", "order_id": txnid})

    # Any other path (including a first POST from the redirect form) -> login step.
    request.session["ci_stage"] = "login"
    return render(request, "connectips_login.html", ctx)


def _render_ci_banks(request, ctx: dict) -> HttpResponse:
    """Render the mock 'select bank' step."""
    ctx["bank"] = request.POST.get("ci_bank")
    return render(request, "connectips_bank.html", ctx)


def _initiate(gateway: str, order: Order, request) -> PaymentResult:
    """Call initiate_payment for a gateway and record the provider reference."""
    manager = _build_manager(gateway, request)

    if gateway == "khalti":
        req = KhaltiRequest(
            return_url=_abs(request, "payments:payments-callback", gateway="khalti"),
            website_url=_abs(request, "payments:payments-home"),
            amount=round(float(order.amount) * 100),  # NPR -> paisa
            purchase_order_id=order.order_id,
            purchase_order_name=order.description or order.order_id,
        )
        result = manager.initiate_payment(PaymentResult, req)
        _raise_if_failed(result, "khalti")
        order.provider_ref = str(result.data.pidx)
        order.lookup_ref = str(result.data.pidx)
    elif gateway == "esewa":
        amount_str = str(order.amount)
        req = EsewaRequest(
            amount=amount_str,
            tax_amount="0",
            total_amount=amount_str,
            transaction_uuid=order.order_id,
            product_code=settings.ESEWA_PRODUCT_CODE,
            product_service_charge="0",
            product_delivery_charge="0",
            signed_field_names="total_amount,transaction_uuid,product_code,tax_amount",
            success_url=_abs(request, "payments:payments-callback", gateway="esewa"),
            failure_url=_abs(request, "payments:payments-failure", gateway="esewa"),
        )
        result = manager.initiate_payment(PaymentResult, req)
        _raise_if_failed(result, "esewa")
        order.provider_ref = result.data.payment_url
        order.lookup_ref = order.order_id  # verification is driven by the callback
    elif gateway == "fonepay":
        if PAYMENT_MODE == PaymentMode.SANDBOX:
            # Sandbox API is down (expired TLS cert): fall back to a simulated QR.
            result = _simulate_fonepay_qr(
                {"amount": str(order.amount), "prn": order.order_id, "remarks1": order.description}
            )
        else:
            req = QrRequest(
                amount=str(order.amount),
                remarks1=order.description or "Payment",
                remarks2="Main Merchant",
                prn=order.order_id,
                merchant_code=settings.FONEPAY_MERCHANT,
                username=settings.FONEPAY_USERNAME,
                password=settings.FONEPAY_PASSWORD,
            )
            result = manager.initiate_payment(PaymentResult, req)
            _raise_if_failed(result, "fonepay")
        order.provider_ref = str(result.data.qr_message)
        order.lookup_ref = "simulated" if getattr(result.data, "simulated", False) else order.order_id
    else:  # connectips
        if not settings.CONNECTIPS_MERCHANT_ID:
            # No merchant credentials configured: fall back to a simulated form
            # so the demo still shows the ConnectIPS POST flow.
            result = _simulate_connectips(order, request)
        else:
            req = ConnectIpsPaymentRequest(
                order_id=order.order_id,
                amount=round(float(order.amount)),
                description=order.description or "Payment",
                success_url=_abs(request, "payments:payments-callback", gateway="connectips"),
                failure_url=_abs(request, "payments:payments-failure", gateway="connectips"),
            )
            result = manager.initiate_payment(PaymentResult, req)
            _raise_if_failed(result, "connectips")
        order.provider_ref = order.order_id  # validation is driven by the callback
        order.lookup_ref = order.order_id

    order.status = "initiated"
    order.save(update_fields=["provider_ref", "lookup_ref", "status", "updated_at"])
    return result.data


def _raise_if_failed(result: PaymentResult, gateway: str) -> None:
    """Raise PaymentError when the gateway rejected the initiation."""
    if not result.success or result.data is None:
        raise PaymentError(result.message or f"{gateway} could not initiate the payment")


def _data_as_dict(data) -> dict:
    """Flatten a verification payload to a plain JSON-able dict.

    The library returns typed (often ``slots=True``) dataclasses whose
    ``__dict__`` is unavailable, plus ``SimpleNamespace`` stand-ins produced by
    the simulated flows. ``asdict`` handles both slotted dataclasses and nested
    values; fall back to ``vars`` for any other object.
    """
    if is_dataclass(data):
        return asdict(data)
    if isinstance(data, (SimpleNamespace,)):
        return vars(data)
    if hasattr(data, "__dict__"):
        return vars(data)
    return dict(data) if isinstance(data, dict) else {}


@require_http_methods(["GET", "POST"])
@csrf_exempt
def callback(request, gateway: str) -> HttpResponse:
    """Handle the provider's callback and verify the payment result."""
    if gateway == "khalti":
        pidx = request.GET.get("pidx") or (request.POST.get("pidx") if request.POST else None)
        return _verify_and_show(request, gateway, pidx, from_callback=True)

    if gateway == "esewa":
        # eSewa delivers a base64-encoded response in the query string.
        b64 = request.GET.get("data") or (request.POST.get("data") if request.POST else None)
        return _verify_and_show(request, gateway, b64, from_callback=True)

    if gateway == "connectips":
        # ConnectIPS posts callback params (TXNID, STATUS, ReferenceID, ...).
        params = dict(request.POST.items()) or dict(request.GET.items())
        if params.get("SIMULATED") == "True":
            # Simulated form posts back here: fake the verification result from
            # the chosen outcome instead of calling the real (cert-required)
            # ConnectIPS verifier.
            status = str(params.get("STATUS", "")).upper()
            order_id = params.get("TXNID") or params.get("REFERENCEID") or ""
            mock = _mock_connectips_result(order_id, success=status == "SUCCESS")
            return _verify_and_show(request, gateway, params, from_callback=True, result=mock)
        return _verify_and_show(request, gateway, params, from_callback=True)

    return HttpResponse("Fonepay is verified via the background monitor.", status=200)


@require_http_methods(["GET", "POST"])
@csrf_exempt
def failure(request, gateway: str) -> HttpResponse:
    """Handle an eSewa payment failure callback and mark the order failed."""
    # eSewa may carry a base64 payload on the failure callback too.
    b64 = request.GET.get("data") or (request.POST.get("data") if request.POST else None)
    if gateway == "esewa" and b64:
        return _verify_and_show(request, gateway, b64, from_callback=True)

    # Without a payload we cannot identify the exact order; mark the most
    # recent initiated one for this gateway as failed so it is not left stranded.
    order = Order.objects.filter(gateway=gateway, status="initiated").order_by("-created_at").first()
    if order is not None:
        order.status = "failed"
        order.save(update_fields=["status", "updated_at"])

    messages.info(request, f"{gateway} payment was cancelled or failed.")
    return redirect("payments:payments-home")


@require_POST
def verify_order(request, order_id: int) -> HttpResponse:
    """Manually re-verify an order (useful for testing and reconciliation)."""
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    order = Order.objects.filter(id=order_id).first()
    if order is None:
        if ajax:
            return JsonResponse({"status": "error", "message": "Order not found."}, status=404)
        messages.error(request, "Order not found.")
        return redirect("payments:payments-home")
    if order.gateway == "esewa":
        # eSewa does not support status lookup by transaction id; verification
        # is only possible by decoding the base64 callback payload. If a prior
        # callback already stored the payload on the order, use it; otherwise
        # there is nothing we can verify yet.
        stored = order.payment_data or {}
        if stored.get("status"):
            ok = str(stored.get("status", "")).upper() == "COMPLETE"
            if ajax:
                return JsonResponse(
                    {
                        "status": "ok",
                        "order_status": "paid" if ok else "failed",
                        "gateway": "esewa",
                        "message": "eSewa " + ("COMPLETE" if ok else "not COMPLETE"),
                    }
                )
            return render(
                request,
                "result.html",
                {
                    "gateway": "esewa",
                    "order": order,
                    "success": ok,
                    "payload": json.dumps(stored, indent=2),
                    "show_toast": True,
                },
            )
        if ajax:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "eSewa status comes from its callback payload; complete or retry the payment first.",
                }
            )
        messages.info(
            request,
            "eSewa is verified from its callback payload. Complete or retry the payment for the status to update.",
        )
        return redirect("payments:payments-home")
    if order.gateway == "connectips":
        # ConnectIPS also verifies from its callback POST parameters (TXNID,
        # STATUS, ...), not from the order id alone, so the same guard applies.
        if ajax:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "ConnectIPS status comes from its callback parameters; re-run the payment first.",
                }
            )
        messages.info(
            request,
            "ConnectIPS is verified from its callback parameters. Re-initiate the payment for the status to update.",
        )
        return redirect("payments:payments-home")
    return _verify_and_show(request, order.gateway, order.lookup_ref, from_callback=False, is_ajax=ajax)


def _verify_and_show(
    request, gateway: str, lookup_ref, from_callback: bool, result=None, is_ajax=False
) -> HttpResponse:
    """Run verify_payment and update the order with the result."""
    if result is not None:
        # Caller supplied a pre-built result (e.g. a simulated ConnectIPS one);
        # skip the real verification round-trip.
        data = result.data
        success = bool(result.success and data)
    else:
        if not lookup_ref:
            messages.error(request, "No verification reference was provided.")
            return redirect("payments:payments-home")

        manager = _build_manager(gateway, request)
        try:
            if gateway == "fonepay":
                content = json.dumps(
                    {
                        "prn": lookup_ref,
                        "merchantCode": settings.FONEPAY_MERCHANT,
                        "username": settings.FONEPAY_USERNAME,
                        "password": settings.FONEPAY_PASSWORD,
                    }
                )
            elif gateway == "connectips":
                # ConnectIPS callback arrives as form params (TXNID, STATUS, ...).
                # The verifier accepts the params as a JSON string or a dict.
                content = lookup_ref if isinstance(lookup_ref, str) else json.dumps(lookup_ref)
            else:
                content = lookup_ref
            result = manager.verify_payment(PaymentResult, content)
        except (ValidationError, PaymentError, NetworkError, AuthenticationError) as exc:
            messages.error(request, f"Verification failed: {exc}")
            return redirect("payments:payments-home")

        data = result.data
        success = bool(result.success and data)

    # Resolve the order to update. Fonepay/ConnectIPS match by the provider
    # reference; for ConnectIPS the callback params carry the TXNID. eSewa's
    # callback payload is base64 wrapping a transaction_uuid that equals the
    # order's lookup_ref, so decode it to find the matching order.
    if isinstance(lookup_ref, dict):
        match_ref = lookup_ref.get("TXNID") or lookup_ref.get("reference_id") or lookup_ref.get("ReferenceID")
    elif gateway == "esewa" and data is not None:
        match_ref = getattr(data, "transaction_uuid", None) or lookup_ref
    else:
        match_ref = lookup_ref

    order = (
        Order.objects.filter(gateway=gateway, lookup_ref=match_ref).first()
        or Order.objects.filter(gateway=gateway, provider_ref=match_ref).first()
    )
    if order is None:
        created_ref = str(match_ref or lookup_ref)
        order = Order.objects.create(
            gateway=gateway,
            order_id=f"{gateway}-verify-{uuid.uuid4().hex[:10]}",
            amount="0",
            status="verified",
            lookup_ref=created_ref,
        )

    _apply_verification(order, result, gateway)

    # A cancelled / failed payment that arrives via the provider's callback
    # (or eSewa's failure_url) is redirected back home with a toast, instead of
    # showing the result page. Only a manual "Verify" shows the result page.
    if from_callback and not success:
        if is_ajax:
            return JsonResponse(
                {
                    "status": "ok",
                    "order_status": "failed",
                    "gateway": gateway,
                    "message": f"{gateway} payment was cancelled or failed.",
                }
            )
        messages.info(request, f"{gateway} payment was cancelled or failed.")
        return redirect("payments:payments-home")

    if is_ajax:
        return JsonResponse(
            {
                "status": "ok",
                "order_status": order.status,
                "gateway": gateway,
                "message": result.message or ("paid" if success else "not paid"),
            }
        )

    return render(
        request,
        "result.html",
        {
            "gateway": gateway,
            "order": order,
            "success": success,
            "payload": json.dumps(_data_as_dict(data), indent=2) if data else result.message,
            # Show a confirmation toast on the result page. Manual "Verify"
            # clicks and ConnectIPS callbacks (which land here with the success
            # outcome) get a toast; provider callbacks for Khalti/eSewa redirect
            # back home instead, so they do not need one.
            "show_toast": (not from_callback) or gateway == "connectips",
        },
    )


def _reconcile_amount(order: Order, data) -> bool:
    """Return whether the verified amount matches the order's amount.

    Khalti (``total_amount``, NPR), eSewa (``total_amount``, NPR) and
    ConnectIPS (``txn_amount``) all return the paid amount; a mismatch means the
    payment settled for less than we expected, which must not be marked "paid".
    """
    verified = getattr(data, "total_amount", None)
    if verified is None:
        verified = getattr(data, "txn_amount", None)
    if verified is None:
        return True  # no amount reported; nothing to reconcile
    try:
        expected = Decimal(str(order.amount))
        actual = Decimal(str(verified))
        return actual == expected
    except (InvalidOperation, ValueError):
        return True  # unparseable amount; don't fail closed on bad data


def _apply_verification(order: Order, result: PaymentResult, gateway: str) -> None:
    """Persist the verification outcome onto an order row."""
    data = result.data
    if data is not None:
        order.payment_data = _data_as_dict(data)
        order.lookup_ref = str(getattr(data, "pidx", None) or order.lookup_ref)

    if result.success and data:
        if _reconcile_amount(order, data):
            order.status = "paid"
        else:
            order.status = "failed"
            if isinstance(order.payment_data, dict):
                order.payment_data["amount_mismatch"] = True
    elif result.message:
        order.status = "failed"
    else:
        order.status = "pending"
    order.save(update_fields=["status", "payment_data", "lookup_ref", "updated_at"])

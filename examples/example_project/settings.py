"""Django settings for the example project."""

import os
from datetime import timedelta
from pathlib import Path

import dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

dotenv.load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-example-only-not-for-production")
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "payments",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "example_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "example_project.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS: list[dict] = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kathmandu"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Payment gateway credentials (loaded from .env via python-dotenv).
# ---------------------------------------------------------------------------

PAID_MODE = os.environ.get("PAID_MODE", "sandbox")

# Public base URL used to build provider callback URLs. If unset, the callback
# URL is derived from the incoming request host instead.
PAYMENT_BASE_URL = os.environ.get("PAID_BASE_URL", "")

# eSewa product code. "EPAYTEST" is the sandbox/test code used in the .NET
# reference demo; replace with your real merchant product code in production.
ESEWA_PRODUCT_CODE = os.environ.get("ESEWA_PRODUCT_CODE", "EPAYTEST")

# Gateway secrets and merchant credentials are supplied from the environment
# (.env). No credentials are hardcoded in this file.
ESEWA_SECRET = os.environ.get("ESEWA_SECRET", "")
KHALTI_SECRET = os.environ.get("KHALTI_SECRET", "")
FONEPAY_SECRET = os.environ.get("FONEPAY_SECRET", "")
FONEPAY_MERCHANT = os.environ.get("FONEPAY_MERCHANT", "")
FONEPAY_USERNAME = os.environ.get("FONEPAY_USERNAME", "")
FONEPAY_PASSWORD = os.environ.get("FONEPAY_PASSWORD", "")

# ConnectIPS demands an RSA certificate plus merchant credentials. The cert is
# a PKCS#12 (.pfx) file secured by a password; fill these in to activate the
# ConnectIPS gateway in the demo.
CONNECTIPS_MERCHANT_ID = os.environ.get("CONNECTIPS_MERCHANT_ID", "")
CONNECTIPS_APP_ID = os.environ.get("CONNECTIPS_APP_ID", "")
CONNECTIPS_APP_NAME = os.environ.get("CONNECTIPS_APP_NAME", "")
CONNECTIPS_APP_PASSWORD = os.environ.get("CONNECTIPS_APP_PASSWORD", "")
CONNECTIPS_CERT_PATH = os.environ.get("CONNECTIPS_CERT_PATH", "")
CONNECTIPS_CERT_PASSWORD = os.environ.get("CONNECTIPS_CERT_PASSWORD", "")

# Credentials used to fill the mock ConnectIPS checkout (also from .env).
CONNECTIPS_DEMO_USER = os.environ.get("CONNECTIPS_DEMO_USER", "nchluser")
CONNECTIPS_DEMO_PASSWORD = os.environ.get("CONNECTIPS_DEMO_PASSWORD", "Nepal@123")
CONNECTIPS_DEMO_CAPTCHA = os.environ.get("CONNECTIPS_DEMO_CAPTCHA", "NCH07")
CONNECTIPS_DEMO_TPIN = os.environ.get("CONNECTIPS_DEMO_TPIN", "123456")
CONNECTIPS_DEMO_OTP = os.environ.get("CONNECTIPS_DEMO_OTP", "987654")

# Fonepay status-monitor settings (see nepali_payment.FonepayPaymentMonitor).

FONEPAY_MONITOR_TIMEOUT = timedelta(minutes=15)
FONEPAY_MONITOR_INTERVAL = timedelta(seconds=5)

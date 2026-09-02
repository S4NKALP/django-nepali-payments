"""
Signing helpers and a response converter used by the gateway services:

- HMAC signing for eSewa (SHA256, base64) and Fonepay (SHA512, lowercase hex).
- RSA signing for ConnectIPS.
- Converting provider responses into typed objects.
"""

import base64
import hashlib
import hmac as _hmac
import json
from functools import lru_cache
from typing import Any, TypeVar

from nepali_payment.exceptions import ValidationError

T = TypeVar("T")


def _validate(message: str, secret: str) -> None:
    if not message:
        raise ValidationError("Message cannot be null or empty.")
    if not secret:
        raise ValidationError("Secret key cannot be null or empty.")


def generate_hmac_sha256_signature(message: str, secret: str) -> str:
    """HMAC-SHA256 digest as base64 (eSewa). Mirrors GenerateHmacSha256Signature."""
    _validate(message, secret)
    digest = _hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def generate_hmac_sha256(message: str, secret: str) -> str:
    """Alias for generate_hmac_sha256_signature."""
    return generate_hmac_sha256_signature(message, secret)


def generate_hmac_sha512(message: str, secret: str) -> str:
    """HMAC-SHA512 digest as lowercase hex (Fonepay).

    Mirrors GenerateHmacSha512. Fonepay rejects base64-encoded dataValidation
    with "Data Validation Failed" (406); only hex reproduces its worked sample.
    """
    _validate(message, secret)
    digest = _hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha512).digest()
    return digest.hex()


def load_rsa_private_key(
    cert_path: str | None = None,
    cert_data: bytes | None = None,
    cert_format: str | None = None,
    cert_password: str | None = None,
):
    """Load an RSA private key from a certificate (used by ConnectIPS).

    Works with PEM, PFX and P12 files. If you pass ``cert_data`` we use that
    straight away; otherwise we read the file at ``cert_path``. PFX/P12 is
    detected from ``cert_format`` or the file ending, otherwise we treat the
    data as PEM.

    Args:
        cert_path: Path to a ``.pfx``, ``.p12`` or ``.pem`` certificate.
        cert_data: The raw certificate bytes (use this instead of ``cert_path``).
        cert_format: ``"pfx"``/``"p12"`` or ``"pem"`` when passing ``cert_data``.
        cert_password: Password for PFX/P12 files (PEM usually has none).

    Returns:
        An RSA private key object from the ``cryptography`` library.

    Raises:
        ValidationError: If no certificate is given, or the key is not RSA.

    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if cert_path is None and not cert_data:
        raise ValidationError("CertPath or CertData is required.")

    if cert_data is not None:
        is_pfx = bool(cert_format and cert_format.lower() in ("pfx", "p12"))
    else:
        with open(cert_path, "rb") as handle:  # cert path is user-supplied
            cert_data = handle.read()
        is_pfx = cert_path.lower().endswith((".pfx", ".p12"))

    if is_pfx:
        key = serialization.pkcs12.load_key_and_certificates(
            cert_data, cert_password.encode("utf-8") if cert_password else None
        )[0]
    else:
        key = serialization.load_pem_private_key(
            cert_data,
            password=cert_password.encode("utf-8") if cert_password else None,
        )

    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValidationError("Certificate does not contain an RSA private key.")
    return key


def generate_rsa_signature(message: str, private_key: Any) -> str:
    """Sign ``message`` with RSA-SHA256 and return it as base64 (ConnectIPS).

    Args:
        message: The text to sign.
        private_key: An RSA key from :func:`load_rsa_private_key`.

    Returns:
        The signature as base64 text.

    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    signature = private_key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("utf-8")


def convert_to(cls: type[T], response: Any) -> T:
    """Best-effort conversion of an arbitrary response into ``cls`` (ResponseConverter.cs)."""
    if response is None:
        return cls()
    if isinstance(response, cls):
        return response
    if isinstance(response, (str, bytes, bytearray)):
        if isinstance(response, bytes):
            response = response.decode("utf-8")
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            data = str(response)
        return _coerce(cls, data)
    if isinstance(response, dict):
        return _coerce(cls, response)
    try:
        return cls(response)
    except (TypeError, ValueError):
        return response  # type: ignore[return-value]


@lru_cache(maxsize=512)
def _to_snake(name: str) -> str:
    """Turn a camelCase or PascalCase name into snake_case."""
    out = []
    for i, ch in enumerate(name):
        if ch.isupper():
            if i > 0 and (name[i - 1].islower() or name[i - 1].isdigit()):
                out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def _coerce(cls: type[T], data: Any) -> T:
    """Build an object of ``cls`` from a dictionary.

    Handles missing keys and camelCase JSON names (``qrMessage`` becomes
    ``qr_message``) without crashing.
    """
    if data is None:
        return cls()
    if isinstance(data, (list, tuple)):
        return [_coerce(cls, item) for item in data]  # type: ignore[return-value]
    try:
        return cls(**data)
    except (TypeError, ValueError):
        keys = getattr(cls, "__dataclass_fields__", None)
        if not keys:
            return data  # type: ignore[return-value]
        if not isinstance(data, dict):
            return data  # type: ignore[return-value]
        snake_map = {_to_snake(k): v for k, v in data.items()}
        filtered = {k: v for k, v in snake_map.items() if k in keys}
        return cls(**filtered)


def decode_base64_content(encoded_content: str) -> str:
    """Decode base64 content, falling back to the raw string (DecodeBase64Content)."""
    try:
        return base64.b64decode(encoded_content).decode("utf-8")
    except (ValueError, TypeError):
        return encoded_content

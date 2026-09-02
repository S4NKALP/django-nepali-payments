"""Locks generate_hmac_sha512 to lowercase hex and sha256 to base64.

These reproduce the worked examples from Fonepay's own
Billing-3rdparty-Integration-Requirement.pdf, mirroring HmacHelperTests.cs.
"""

import re
from dataclasses import dataclass

import pytest

from nepali_payment.exceptions import ValidationError
from nepali_payment.helpers import (
    _coerce,
    convert_to,
    decode_base64_content,
    generate_hmac_sha256,
    generate_hmac_sha256_signature,
    generate_hmac_sha512,
)

SECRET_KEY = "a7e3512f5032480a83137793cb2021dc"


def test_generate_hmac_sha512_qr_request_without_tax_refund_matches_fonepay_sample():
    message = "14,5d76d323-d1f6-4a38-8231-0063f9581c98,NBQM,test1,test2"
    signature = generate_hmac_sha512(message, SECRET_KEY)
    assert signature == (
        "43d2f0939e58e038c3122cc1e65f86af01998dce3e9f70a41a664dc0dbd45dfd"
        "74b4c4cbb77afef8a5ae9854ab48fcbd7edfc93156f663a8c60f28830eaca7d7"
    )


def test_generate_hmac_sha512_check_qr_status_matches_fonepay_sample():
    message = "5d76d323-d1f6-4a38-8231-0063f9581c98,NBQM"
    signature = generate_hmac_sha512(message, SECRET_KEY)
    assert signature == (
        "de5fd3bbbd7d36c766a47c0a137e41de7587028d2f6e3deacb5bebe309923268"
        "76a6fba4f9ccfd55a1d302a81aba94733d6c1db04f749483be63b619a9b032b7"
    )


def test_generate_hmac_sha512_tax_refund_matches_fonepay_sample():
    message = "35132,e85d2ae7-e342-4a1c-81d7-536867a6720e,IN2_e85d2ae7-e342-4a1c-81d7-536867a6720e,2076.09.29,14,NBQM"
    signature = generate_hmac_sha512(message, SECRET_KEY)
    assert signature == (
        "4b3fbd3dbfdf2e6d5a2999e8ace63e3b47153dd91c4c17846ef473b12211b0df"
        "4acc9e9dc4f814530880f977f665bccc7f1555310918a1d0ff2a57097b4eb8a4"
    )


def test_generate_hmac_sha256_signature_stays_base64_esewa_unaffected():
    signature = generate_hmac_sha256_signature("total_amount=100,transaction_uuid=abc,product_code=EPAYTEST", "secret")
    assert re.match(r"^[A-Za-z0-9+/]+={0,2}$", signature)


def test_generate_hmac_sha512_is_lowercase_hex():
    signature = generate_hmac_sha512("14,NBQM,test", SECRET_KEY)
    assert re.match(r"^[0-9a-f]{128}$", signature)


def test_generate_hmac_sha256_alias_matches_signature():
    message = "total_amount=100,transaction_uuid=abc,product_code=EPAYTEST"
    assert generate_hmac_sha256(message, "secret") == generate_hmac_sha256_signature(message, "secret")


def test_validate_rejects_empty():
    with pytest.raises(ValidationError):
        generate_hmac_sha512("", "secret")
    with pytest.raises(ValidationError):
        generate_hmac_sha512("message", "")


@dataclass
class _Sample:
    pidx: str | None = None
    status: str | None = None


def test_coerce_handles_camel_case_and_missing_keys():
    obj = _coerce(_Sample, {"pidx": "p", "status": "ok", "Unknown": "x"})
    assert obj.pidx == "p"
    assert obj.status == "ok"


def test_coerce_list_and_non_dataclass():
    assert _coerce(_Sample, [{"pidx": "a"}, {"pidx": "b"}]) == [_Sample(pidx="a"), _Sample(pidx="b")]
    assert _coerce(dict, {"a": 1}) == {"a": 1}


def test_convert_to_none_returns_default():
    assert convert_to(str, None) == ""
    assert convert_to(_Sample, None) == _Sample()


def test_convert_to_handles_bytes_and_non_json():
    assert convert_to(str, "some text") == "some text"
    obj = convert_to(_Sample, b'{"pidx": "q"}')
    assert obj.pidx == "q"


def test_convert_to_does_best_effort_fallbacks():
    # Non-data response becomes a function-call attempt, then raw passthrough.
    assert convert_to(list, 42) == 42


def test_decode_base64_content_falls_back_to_raw():
    assert decode_base64_content("not base64 123 !") == "not base64 123 !"
    assert decode_base64_content("aGVsbG8=") == "hello"


def test_load_rsa_private_key_from_pem_bytes():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from nepali_payment.helpers import generate_rsa_signature, load_rsa_private_key

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    loaded = load_rsa_private_key(cert_data=pem)
    signature = generate_rsa_signature("hello", loaded)
    assert signature


def test_load_rsa_private_key_rejects_non_rsa_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from nepali_payment.helpers import load_rsa_private_key

    ec_key = ec.generate_private_key(ec.SECP256R1())
    pem = ec_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(ValidationError):
        load_rsa_private_key(cert_data=pem)


def test_load_rsa_private_key_requires_certificate():
    from nepali_payment.helpers import load_rsa_private_key

    with pytest.raises(ValidationError):
        load_rsa_private_key(cert_path=None, cert_data=None)

import time

import pytest

from app.signatures import SignatureError, sign_shopify, sign_stripe, verify_shopify, verify_stripe

BODY = b'{"id": 1, "total_price": "52.32"}'


def test_shopify_valid():
    verify_shopify(BODY, sign_shopify(BODY, "s3cret"), "s3cret")


@pytest.mark.parametrize("header,secret,why", [
    (None, "s3cret", "missing"),
    ("not-the-hmac", "s3cret", "does not match"),
    (sign_shopify(BODY, "other"), "s3cret", "does not match"),
    (sign_shopify(BODY, "s3cret"), "", "no signing secret"),
])
def test_shopify_rejects(header, secret, why):
    with pytest.raises(SignatureError, match=why):
        verify_shopify(BODY, header, secret)


def test_shopify_body_tamper():
    header = sign_shopify(BODY, "s3cret")
    with pytest.raises(SignatureError):
        verify_shopify(BODY.replace(b"52.32", b"0.01"), header, "s3cret")


def test_stripe_valid_and_returns_timestamp():
    ts = int(time.time())
    assert verify_stripe(BODY, sign_stripe(BODY, "whsec_x", ts), "whsec_x") == ts


def test_stripe_accepts_any_matching_v1_during_secret_rotation():
    ts = int(time.time())
    good = sign_stripe(BODY, "whsec_new", ts).split(",")[1]
    header = f"t={ts},v1={'0' * 64},{good}"
    verify_stripe(BODY, header, "whsec_new")


@pytest.mark.parametrize("header,why", [
    (None, "missing"),
    ("v1=abc", "no timestamp"),
    ("t=abc,v1=abc", "bad timestamp"),
    ("t=123", "no timestamp or no v1"),
])
def test_stripe_malformed(header, why):
    with pytest.raises(SignatureError, match=why):
        verify_stripe(BODY, header, "whsec_x")


def test_stripe_wrong_secret():
    with pytest.raises(SignatureError, match="does not match"):
        verify_stripe(BODY, sign_stripe(BODY, "whsec_other"), "whsec_x")


def test_stripe_old_timestamp_is_rejected_even_if_signed():
    old = int(time.time()) - 3600
    with pytest.raises(SignatureError, match="tolerance"):
        verify_stripe(BODY, sign_stripe(BODY, "whsec_x", old), "whsec_x")

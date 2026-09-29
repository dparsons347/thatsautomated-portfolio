"""Webhook signature checks. Both work on the raw request body, before any JSON parsing."""
import base64
import hashlib
import hmac
import time


class SignatureError(Exception):
    pass


def verify_shopify(raw_body: bytes, hmac_header: str | None, secret: str) -> None:
    """Shopify signs the raw body with HMAC-SHA256 and sends it base64 encoded in X-Shopify-Hmac-Sha256."""
    if not hmac_header:
        raise SignatureError("missing X-Shopify-Hmac-Sha256")
    if not secret:
        raise SignatureError("no signing secret configured for this store")
    expected = base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(expected, hmac_header.strip()):
        raise SignatureError("HMAC does not match")


def verify_stripe(
    raw_body: bytes,
    sig_header: str | None,
    secret: str,
    tolerance_seconds: int = 300,
    now: float | None = None,
) -> int:
    """Stripe-Signature is "t=<unix>,v1=<hex>[,v1=<hex>...]". The signed payload is "<t>.<raw body>".

    Returns the timestamp. Rejects anything outside the tolerance window so a captured
    request can't be replayed later with a valid signature.
    """
    if not sig_header:
        raise SignatureError("missing Stripe-Signature")
    if not secret:
        raise SignatureError("no Stripe webhook secret configured")
    timestamp = None
    candidates = []
    for part in sig_header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                raise SignatureError("bad timestamp in Stripe-Signature") from None
        elif key == "v1":
            candidates.append(value)
    if timestamp is None or not candidates:
        raise SignatureError("Stripe-Signature has no timestamp or no v1 signature")
    signed = f"{timestamp}.".encode() + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise SignatureError("signature does not match")
    now = time.time() if now is None else now
    if abs(now - timestamp) > tolerance_seconds:
        raise SignatureError(f"timestamp outside the {tolerance_seconds}s tolerance")
    return timestamp


# Helpers used by the tests and the test-data scripts to produce valid signatures.

def sign_shopify(raw_body: bytes, secret: str) -> str:
    return base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()).decode()


def sign_stripe(raw_body: bytes, secret: str, timestamp: int | None = None) -> str:
    timestamp = int(time.time()) if timestamp is None else timestamp
    sig = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"

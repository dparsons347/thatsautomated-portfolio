"""Slack request signing (https://api.slack.com/authentication/verifying-requests-from-slack)."""
from __future__ import annotations

import hashlib
import hmac
import time

MAX_AGE_SECONDS = 300


def sign(secret: str, timestamp: str, body: str) -> str:
    base = f"v0:{timestamp}:{body}".encode()
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, signature: str, body: str, *, now: float | None = None) -> tuple[bool, str]:
    if not secret:
        return False, "signing secret not configured"
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False, "bad timestamp"
    if abs((now if now is not None else time.time()) - ts) > MAX_AGE_SECONDS:
        return False, "timestamp too old (possible replay)"
    if not hmac.compare_digest(sign(secret, timestamp, body), signature or ""):
        return False, "signature mismatch"
    return True, "ok"

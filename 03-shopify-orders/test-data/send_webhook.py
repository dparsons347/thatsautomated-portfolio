"""Send a signed (or deliberately mis-signed) test webhook to the receiver.

Real Shopify and Stripe events are what the Loom uses. This is for checking a fresh deploy
before the stores are wired up, and for the bad-signature beat.

  python3 test-data/send_webhook.py https://orders.thatsautomated.com shopify-order --secret <store A key>
  python3 test-data/send_webhook.py https://orders.thatsautomated.com shopify-order --bad
  python3 test-data/send_webhook.py https://orders.thatsautomated.com stripe-invoice --secret whsec_...
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.signatures import sign_shopify, sign_stripe  # noqa: E402
from tests import payloads  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("kind", choices=["shopify-order", "stripe-invoice"])
    ap.add_argument("--secret", default="")
    ap.add_argument("--shop", default="loblolly-candle-co.myshopify.com")
    ap.add_argument("--email", default="jordan.lee@example.com")
    ap.add_argument("--bad", action="store_true", help="sign with the wrong key")
    args = ap.parse_args()
    secret = "definitely-not-the-key" if args.bad else args.secret

    if args.kind == "shopify-order":
        body = json.dumps(payloads.shopify_order(email=args.email, name="#9001")).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Topic": "orders/create",
            "X-Shopify-Shop-Domain": args.shop,
            "X-Shopify-Event-Id": str(uuid.uuid4()),
            "X-Shopify-Hmac-Sha256": sign_shopify(body, secret),
        }
        url = args.base_url.rstrip("/") + "/webhooks/shopify"
    else:
        body = json.dumps(payloads.stripe_event("invoice.paid", payloads.stripe_invoice(email=args.email))).encode()
        headers = {"Content-Type": "application/json", "Stripe-Signature": sign_stripe(body, secret)}
        url = args.base_url.rstrip("/") + "/webhooks/stripe"

    r = httpx.post(url, content=body, headers=headers, timeout=10)
    print(r.status_code, r.text)


if __name__ == "__main__":
    main()

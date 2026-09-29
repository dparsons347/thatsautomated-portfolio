#!/usr/bin/env bash
# The Loom's "bad webhook" beat: a request that claims to be Shopify but isn't signed with the store's key.
# Expect: 401 {"error":"HMAC does not match"} and a new row in rejected_requests.
URL="${1:-https://orders.thatsautomated.com}"
curl -sS -X POST "$URL/webhooks/shopify" \
  -H 'Content-Type: application/json' \
  -H 'X-Shopify-Topic: orders/create' \
  -H 'X-Shopify-Shop-Domain: store-a.myshopify.com' \
  -H 'X-Shopify-Event-Id: forged-1' \
  -H 'X-Shopify-Hmac-Sha256: bm90IHRoZSByZWFsIHNpZ25hdHVyZQ==' \
  -d '{"id": 1, "name": "#6666", "email": "attacker@example.com", "total_price": "0.01", "financial_status": "paid"}' \
  -w '\nHTTP %{http_code}\n'

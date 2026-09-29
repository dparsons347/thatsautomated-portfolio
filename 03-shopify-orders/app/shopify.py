"""Shopify webhook topics mapped onto the shared schema."""
from . import store

PAID_STATES = {"paid", "partially_refunded", "refunded"}
ORDER_TOPICS = {"orders/create", "orders/updated", "orders/paid", "orders/cancelled", "orders/fulfilled"}
FULFILLMENT_TOPICS = {"fulfillments/create", "fulfillments/update"}


def event_key(shop_domain: str, topic: str, headers) -> str | None:
    """X-Shopify-Event-Id is shared by every webhook one event produces (orders/create and
    orders/paid can come from the same checkout), so the key includes the topic and the shop.
    X-Shopify-Webhook-Id is the fallback for older deliveries. Both stay the same on retries."""
    ident = headers.get("x-shopify-event-id") or headers.get("x-shopify-webhook-id")
    if not ident:
        return None
    return f"{shop_domain}:{topic}:{ident}"


def handle(conn, channel_row: dict, topic: str, body: dict) -> tuple[str, str]:
    """Apply one webhook. Returns (outcome, detail) for the event log."""
    if topic in ORDER_TOPICS:
        return apply_order(conn, channel_row, body)
    if topic == "refunds/create":
        return apply_refund(conn, channel_row, body)
    if topic in FULFILLMENT_TOPICS:
        return apply_fulfillment(conn, channel_row, body)
    return "ignored", f"topic {topic} is not used"


def _customer(conn, order: dict) -> int | None:
    c = order.get("customer") or {}
    addr = order.get("shipping_address") or order.get("billing_address") or {}
    return store.upsert_customer(
        conn,
        order.get("email") or order.get("contact_email") or c.get("email"),
        c.get("first_name") or addr.get("first_name"),
        c.get("last_name") or addr.get("last_name"),
        order.get("phone") or c.get("phone") or addr.get("phone"),
    )


def apply_order(conn, channel_row: dict, o: dict) -> tuple[str, str]:
    financial = o.get("financial_status")
    paid_at = (o.get("processed_at") or o.get("created_at")) if financial in PAID_STATES else None
    order_id, applied = store.upsert_order(
        conn,
        channel_id=channel_row["id"],
        external_id=str(o["id"]),
        order_number=o.get("name") or str(o.get("order_number") or o["id"]),
        customer_id=_customer(conn, o),
        currency=o.get("currency") or "USD",
        subtotal=store.money(o.get("subtotal_price")),
        total=store.money(o.get("total_price")),
        financial_status=financial,
        fulfillment_status=o.get("fulfillment_status") or "unfulfilled",
        placed_at=o.get("created_at"),
        paid_at=paid_at,
        cancelled_at=o.get("cancelled_at"),
        source_updated_at=o.get("updated_at"),
        raw=o,
    )
    if not applied:
        return "stale", f"order {o.get('name')} already has a newer update"

    store.replace_lines(conn, order_id, [
        {
            "external_id": str(li["id"]),
            "sku": li.get("sku"),
            "title": li.get("title") or li.get("name") or "",
            "quantity": int(li.get("quantity") or 0),
            "unit_price": store.money(li.get("price")),
        }
        for li in o.get("line_items") or []
    ])

    order = conn.execute("SELECT * FROM orders WHERE id = %s", (order_id,)).fetchone()
    # Order payloads carry their refunds and fulfillments too. Applying them here as well means a
    # missed refunds/create or fulfillments/create webhook is repaired by the next orders/updated.
    for r in o.get("refunds") or []:
        _refund_rows(conn, order, r)
    for f in o.get("fulfillments") or []:
        store.upsert_fulfillment(conn, order, channel_row, _fulfillment_fields(f))
    return "applied", f"order {order['order_number']}"


def _refund_amount(refund: dict):
    return sum(
        (store.money(t.get("amount")) for t in refund.get("transactions") or []
         if t.get("kind") == "refund" and t.get("status") == "success"),
        store.money(0),
    )


def _refund_rows(conn, order: dict, refund: dict) -> None:
    store.upsert_refund(
        conn, order["id"], "shopify", refund["id"], _refund_amount(refund),
        refund.get("processed_at") or refund.get("created_at"),
    )


def apply_refund(conn, channel_row: dict, r: dict) -> tuple[str, str]:
    order = store.find_order(conn, channel_row["id"], r["order_id"])
    if order is None:
        raise store.Deferred(f"refund {r['id']} for order {r['order_id']} arrived before the order")
    _refund_rows(conn, order, r)
    return "applied", f"refund {store.money(_refund_amount(r))} on {order['order_number']}"


def _fulfillment_fields(f: dict) -> dict:
    urls = f.get("tracking_urls") or []
    numbers = f.get("tracking_numbers") or []
    return {
        "external_id": str(f["id"]),
        "status": f.get("status") or "open",
        "shipment_status": f.get("shipment_status"),
        "tracking_company": f.get("tracking_company"),
        "tracking_number": f.get("tracking_number") or (numbers[0] if numbers else None),
        "tracking_url": f.get("tracking_url") or (urls[0] if urls else None),
    }


def apply_fulfillment(conn, channel_row: dict, f: dict) -> tuple[str, str]:
    order = store.find_order(conn, channel_row["id"], f["order_id"])
    if order is None:
        raise store.Deferred(f"fulfillment {f['id']} for order {f['order_id']} arrived before the order")
    fields = _fulfillment_fields(f)
    store.upsert_fulfillment(conn, order, channel_row, fields)
    return "applied", f"fulfillment {fields['status']} on {order['order_number']}"

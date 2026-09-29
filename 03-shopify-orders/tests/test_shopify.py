from datetime import timedelta

from tests import payloads as p


def test_same_customer_on_two_stores_is_one_customer(send_shopify, sql):
    a = send_shopify("orders/create", p.shopify_order(email="Jordan.Lee@Example.com ", name="#1001"), store="a")
    b = send_shopify("orders/create", p.shopify_order(email="jordan.lee@example.com", name="#1001"), store="b")
    assert a.status_code == 200 and a.json()["result"] == "applied"
    assert b.status_code == 200 and b.json()["result"] == "applied"
    customers = sql("SELECT * FROM customers")
    assert len(customers) == 1 and customers[0]["email"] == "jordan.lee@example.com"
    rows = sql("SELECT channel, order_number, customer_orders, status FROM orders_unified ORDER BY channel")
    assert [(r["channel"], r["order_number"], r["customer_orders"]) for r in rows] == [
        ("Store A", "#1001", 2), ("Store B", "#1001", 2)]
    assert all(r["status"] == "paid, awaiting fulfillment" for r in rows)


def test_order_lines_and_totals(send_shopify, sql):
    order = p.shopify_order(lines=[
        {"sku": "A", "title": "Candle", "quantity": 2, "price": "24.00"},
        {"sku": "B", "title": "Wick trimmer", "quantity": 1, "price": "12.50"},
    ])
    send_shopify("orders/create", order)
    o = sql("SELECT * FROM orders")[0]
    assert str(o["subtotal"]) == "60.50" and str(o["total"]) == order["total_price"]
    lines = sql("SELECT sku, quantity, unit_price FROM order_lines ORDER BY sku")
    assert [(l["sku"], l["quantity"], str(l["unit_price"])) for l in lines] == [("A", 2, "24.00"), ("B", 1, "12.50")]


def test_replayed_shopify_webhook_is_ignored(send_shopify, sql):
    order = p.shopify_order()
    first = send_shopify("orders/create", order, event_id="same-event")
    again = send_shopify("orders/create", order, event_id="same-event")
    assert first.json()["result"] == "applied"
    assert again.status_code == 200 and again.json()["result"] == "replay"
    assert len(sql("SELECT * FROM orders")) == 1
    ev = sql("SELECT replays, outcome FROM webhook_events")
    assert ev[0]["replays"] == 1 and ev[0]["outcome"] == "applied"


def test_same_event_id_on_different_topics_is_not_a_replay(send_shopify, sql):
    order = p.shopify_order()
    send_shopify("orders/create", order, event_id="checkout-1")
    r = send_shopify("orders/paid", order, event_id="checkout-1")
    assert r.json()["result"] == "applied"


def test_bad_hmac_is_rejected_and_logged_while_good_ones_land(send_shopify, sql):
    bad = send_shopify("orders/create", p.shopify_order(name="#1002"), secret="wrong-secret")
    assert bad.status_code == 401
    rej = sql("SELECT source, reason, headers FROM rejected_requests")
    assert rej[0]["source"] == "shopify" and rej[0]["reason"] == "HMAC does not match"
    assert rej[0]["headers"]["x-shopify-topic"] == "orders/create"
    good = send_shopify("orders/create", p.shopify_order(name="#1003"))
    assert good.status_code == 200
    assert [r["order_number"] for r in sql("SELECT order_number FROM orders")] == ["#1003"]


def test_store_b_secret_does_not_work_for_store_a(send_shopify):
    r = send_shopify("orders/create", p.shopify_order(), store="a", secret="shpss_store_b_secret")
    assert r.status_code == 401


def test_unknown_shop_is_rejected(send_shopify, sql):
    r = send_shopify("orders/create", p.shopify_order(), shop="someone-else.myshopify.com")
    assert r.status_code == 401
    assert "unknown shop" in sql("SELECT reason FROM rejected_requests")[0]["reason"]


def test_stale_update_does_not_overwrite_newer(send_shopify, sql):
    placed = p.now() - timedelta(hours=1)
    order = p.shopify_order(placed=placed, updated=placed + timedelta(minutes=30))
    send_shopify("orders/updated", order)
    older = dict(order, updated_at=p.iso(placed + timedelta(minutes=10)), financial_status="pending")
    r = send_shopify("orders/updated", older)
    assert r.json()["result"] == "stale"
    assert sql("SELECT financial_status FROM orders")[0]["financial_status"] == "paid"


def test_unused_topic_is_logged_and_ignored(send_shopify, sql):
    r = send_shopify("products/update", {"id": 1})
    assert r.json()["result"] == "ignored"
    assert sql("SELECT outcome FROM webhook_events")[0]["outcome"] == "ignored"


def test_refund_before_order_is_deferred_then_lands(send_shopify, sql):
    order = p.shopify_order()
    refund = p.shopify_refund(order["id"], amount="10.00")
    early = send_shopify("refunds/create", refund, event_id="refund-1")
    assert early.status_code == 503
    assert sql("SELECT * FROM webhook_events") == []  # not recorded, so Shopify's retry is not a "replay"
    send_shopify("orders/create", order)
    retry = send_shopify("refunds/create", refund, event_id="refund-1")
    assert retry.json()["result"] == "applied"
    assert str(sql("SELECT total_refunded FROM orders")[0]["total_refunded"]) == "10.00"


def test_refund_seen_twice_via_order_update_counts_once(send_shopify, sql):
    order = p.shopify_order()
    send_shopify("orders/create", order)
    refund = p.shopify_refund(order["id"], amount="15.00")
    send_shopify("refunds/create", refund)
    later = dict(order, refunds=[refund], financial_status="partially_refunded",
                 updated_at=p.iso(p.now() + timedelta(minutes=1)))
    send_shopify("orders/updated", later)
    assert str(sql("SELECT total_refunded FROM orders")[0]["total_refunded"]) == "15.00"


def test_fulfillment_marks_order_and_queues_one_shipped_email(send_shopify, sql):
    order = p.shopify_order()
    send_shopify("orders/create", order)
    f = p.shopify_fulfillment(order["id"])
    send_shopify("fulfillments/create", f)
    send_shopify("fulfillments/update", dict(f, shipment_status="in_transit"))
    row = sql("SELECT status, tracking FROM orders_unified")[0]
    assert row["status"] == "fulfilled" and row["tracking"] == "1Z999AA10123456784"
    notes = sql("SELECT kind, payload FROM notifications")
    assert len(notes) == 1 and notes[0]["kind"] == "shipped"
    assert notes[0]["payload"]["to_email"] == "jordan.lee@example.com"
    assert notes[0]["payload"]["tracking_url"].endswith("1Z999AA10123456784")
    assert notes[0]["payload"]["store"] == "Store A"


def test_pending_fulfillment_does_not_mark_fulfilled(send_shopify, sql):
    order = p.shopify_order()
    send_shopify("orders/create", order)
    send_shopify("fulfillments/create", p.shopify_fulfillment(order["id"], status="pending"))
    assert sql("SELECT fulfilled_at FROM orders")[0]["fulfilled_at"] is None
    assert sql("SELECT * FROM notifications") == []


def test_fulfillment_before_order_is_deferred(send_shopify):
    r = send_shopify("fulfillments/create", p.shopify_fulfillment(123))
    assert r.status_code == 503


def test_order_without_email_still_lands(send_shopify, sql):
    order = p.shopify_order(email=None)
    order["customer"] = None
    assert send_shopify("orders/create", order).json()["result"] == "applied"
    assert sql("SELECT customer_id FROM orders")[0]["customer_id"] is None

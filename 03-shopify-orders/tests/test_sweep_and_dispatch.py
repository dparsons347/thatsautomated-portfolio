from datetime import timedelta

import httpx

from app import db, dispatcher
from tests import payloads as p
from tests.conftest import ADMIN


def _old_paid_order(send_shopify, name="#1001", hours=3, store="a", **kw):
    order = p.shopify_order(name=name, placed=p.now() - timedelta(hours=hours), **kw)
    send_shopify("orders/create", order, store=store)
    return order


def sweep(client):
    r = client.post("/admin/sweep", headers={"Authorization": f"Bearer {ADMIN}"})
    assert r.status_code == 200
    return r.json()["marked_stuck"]


def test_sweep_needs_the_admin_token(client):
    assert client.post("/admin/sweep").status_code == 401
    assert client.post("/admin/sweep", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_sweep_marks_overdue_paid_order_once(client, send_shopify, sql):
    _old_paid_order(send_shopify, "#1004")
    assert sweep(client) == [{"order": "#1004", "store": "Store A"}]
    assert sweep(client) == []
    kinds = sorted(n["kind"] for n in sql("SELECT kind FROM notifications"))
    assert kinds == ["delayed", "stuck_alert"]
    assert sql("SELECT status FROM orders_unified")[0]["status"] == "STUCK"


def test_sweep_leaves_alone_what_it_should(client, send_shopify, send_stripe, sql):
    _old_paid_order(send_shopify, "#2001", hours=0.25)                       # too recent
    _old_paid_order(send_shopify, "#2002", paid=False)                       # not paid
    _old_paid_order(send_shopify, "#2003", cancelled_at=p.iso(p.now()))      # cancelled
    shipped = _old_paid_order(send_shopify, "#2004")
    send_shopify("fulfillments/create", p.shopify_fulfillment(shipped["id"]))  # fulfilled
    refunded = _old_paid_order(send_shopify, "#2005")
    send_shopify("refunds/create", p.shopify_refund(refunded["id"], amount=refunded["total_price"]))  # fully refunded
    send_stripe(p.stripe_event("invoice.paid", p.stripe_invoice()))          # wholesale, not swept
    with db.transaction() as conn:
        conn.execute("UPDATE orders SET paid_at = now() - interval '3 hours' WHERE paid_at IS NOT NULL AND order_number <> '#2001'")
    _old_paid_order(send_shopify, "#2006", store="b")                        # the only one
    assert [o["order"] for o in sweep(client)] == ["#2006"]


def test_fulfillment_after_stuck_clears_status(client, send_shopify, sql):
    order = _old_paid_order(send_shopify, "#1005")
    sweep(client)
    send_shopify("fulfillments/create", p.shopify_fulfillment(order["id"]))
    assert sql("SELECT status FROM orders_unified")[0]["status"] == "fulfilled"


def _transport(status_codes, seen):
    codes = iter(status_codes)

    def handler(request: httpx.Request):
        seen.append(request)
        code = next(codes)
        if code == "down":
            raise httpx.ConnectError("connection refused")
        return httpx.Response(code, text="ok")
    return httpx.MockTransport(handler)


def _dispatch(codes, seen, max_attempts=3):
    with db.transaction() as conn:
        return dispatcher.run(conn, "http://n8n.test/hook", "k", max_attempts,
                              client=httpx.Client(transport=_transport(codes, seen)))


def test_dispatch_sends_with_key_and_marks_sent(client, send_shopify, sql):
    order = p.shopify_order()
    send_shopify("orders/create", order)
    send_shopify("fulfillments/create", p.shopify_fulfillment(order["id"]))
    seen = []
    assert _dispatch([200], seen)["sent"] == 1
    assert seen[0].headers["X-Webhook-Key"] == "k"
    assert b'"kind":"shipped"' in seen[0].content.replace(b" ", b"")
    assert sql("SELECT status, attempts FROM notifications")[0] == {"status": "sent", "attempts": 1}
    assert _dispatch([], seen)["sent"] == 0  # nothing left to send


def test_dispatch_retries_when_n8n_is_down_then_gives_up(client, send_shopify, sql):
    order = p.shopify_order()
    send_shopify("orders/create", order)
    send_shopify("fulfillments/create", p.shopify_fulfillment(order["id"]))
    seen = []
    assert _dispatch(["down"], seen)["retry"] == 1
    n = sql("SELECT status, attempts, last_error, next_attempt_at > now() AS later FROM notifications")[0]
    assert n["status"] == "pending" and n["attempts"] == 1 and "ConnectError" in n["last_error"] and n["later"]
    assert _dispatch([], seen)["retry"] == 0  # not due yet
    for code in (500, 503):
        with db.transaction() as conn:
            conn.execute("UPDATE notifications SET next_attempt_at = now()")
        _dispatch([code], seen)
    n = sql("SELECT status, attempts FROM notifications")[0]
    assert n == {"status": "failed", "attempts": 3}


def test_dispatch_backoff_doubles_and_caps():
    assert [dispatcher.backoff(a).seconds // 60 for a in (1, 2, 3, 4, 7, 10)] == [1, 2, 4, 8, 60, 60]


def test_health_reports_backlog(client, send_shopify):
    assert client.get("/health").json()["ok"] is True
    with db.transaction() as conn:
        conn.execute("""INSERT INTO notifications (kind, dedupe_key, payload, status)
                        VALUES ('stuck_alert', 'x', '{}', 'failed')""")
    r = client.get("/health")
    assert r.status_code == 503 and r.json()["failed"] == 1

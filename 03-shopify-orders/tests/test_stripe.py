from tests import payloads as p


def test_paid_invoice_is_a_wholesale_order_for_the_same_customer(send_shopify, send_stripe, sql):
    send_shopify("orders/create", p.shopify_order(email="jordan.lee@example.com"))
    r = send_stripe(p.stripe_event("invoice.paid", p.stripe_invoice(email="JORDAN.LEE@example.com", amount=38400)))
    assert r.status_code == 200 and r.json()["result"] == "applied"
    assert len(sql("SELECT * FROM customers")) == 1
    w = sql("SELECT * FROM orders_unified WHERE channel = 'Wholesale'")[0]
    assert w["order_number"] == "WHL-0001" and str(w["total"]) == "384.00" and w["customer_orders"] == 2
    line = sql("SELECT sku, quantity, unit_price FROM order_lines l JOIN orders o ON o.id = l.order_id JOIN channels c ON c.id = o.channel_id WHERE c.code = 'wholesale'")[0]
    assert (line["sku"], line["quantity"], str(line["unit_price"])) == ("CNDL-CEDAR-8-CS24", 2, "192.00")
    assert str(sql("SELECT amount FROM payments")[0]["amount"]) == "384.00"


def test_stripe_replay_is_ignored_one_payment_row(send_stripe, sql):
    event = p.stripe_event("invoice.paid", p.stripe_invoice())
    assert send_stripe(event).json()["result"] == "applied"
    again = send_stripe(event)
    assert again.status_code == 200 and again.json()["result"] == "replay"
    assert len(sql("SELECT * FROM payments")) == 1
    assert sql("SELECT replays FROM webhook_events")[0]["replays"] == 1


def test_bad_stripe_signature_rejected(send_stripe, sql):
    r = send_stripe(p.stripe_event("invoice.paid", p.stripe_invoice()), secret="whsec_wrong")
    assert r.status_code == 401
    assert sql("SELECT * FROM orders") == []
    assert sql("SELECT source FROM rejected_requests")[0]["source"] == "stripe"


def test_old_stripe_signature_rejected(send_stripe):
    import time
    r = send_stripe(p.stripe_event("invoice.paid", p.stripe_invoice()), timestamp=int(time.time()) - 900)
    assert r.status_code == 401


def test_refund_links_through_invoice_payment_on_new_api_versions(send_stripe, sql):
    inv = p.stripe_invoice(amount=38400)
    send_stripe(p.stripe_event("invoice.paid", inv))
    send_stripe(p.stripe_event("invoice_payment.paid", p.stripe_invoice_payment(inv["id"], "pi_test_1")))
    r = send_stripe(p.stripe_event("charge.refunded", p.stripe_charge_refunded("pi_test_1", 9600)))
    assert r.json()["result"] == "applied"
    assert str(sql("SELECT total_refunded FROM orders")[0]["total_refunded"]) == "96.00"


def test_running_refund_total_on_one_charge(send_stripe, sql):
    inv = p.stripe_invoice(amount=38400, payment_intent="pi_test_2")
    send_stripe(p.stripe_event("invoice.paid", inv))
    send_stripe(p.stripe_event("charge.refunded", p.stripe_charge_refunded("pi_test_2", 9600, charge_id="ch_1")))
    send_stripe(p.stripe_event("charge.refunded", p.stripe_charge_refunded("pi_test_2", 19200, charge_id="ch_1")))
    assert str(sql("SELECT total_refunded FROM orders")[0]["total_refunded"]) == "192.00"
    send_stripe(p.stripe_event("charge.refunded", p.stripe_charge_refunded("pi_test_2", 38400, charge_id="ch_1")))
    assert sql("SELECT status FROM orders_unified")[0]["status"] == "refunded"


def test_invoice_payment_before_invoice_is_deferred(send_stripe):
    r = send_stripe(p.stripe_event("invoice_payment.paid", p.stripe_invoice_payment("in_unknown", "pi_x")))
    assert r.status_code == 503


def test_refund_for_unknown_payment_raises_an_alert(send_stripe, sql):
    r = send_stripe(p.stripe_event("charge.refunded", p.stripe_charge_refunded("pi_not_ours")))
    assert r.json()["result"] == "unmatched"
    n = sql("SELECT kind, payload FROM notifications")
    assert n[0]["kind"] == "unmatched_refund" and n[0]["payload"]["payment_intent"] == "pi_not_ours"


def test_unused_stripe_event_is_ignored(send_stripe):
    assert send_stripe(p.stripe_event("customer.created", {"id": "cus_1"})).json()["result"] == "ignored"

"""Payload builders shaped like the real webhooks (trimmed to the fields that matter)."""
import itertools
from datetime import datetime, timedelta, timezone

_ids = itertools.count(5_000_000_001)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone(timedelta(hours=-5))).isoformat(timespec="seconds")


def now() -> datetime:
    return datetime.now(timezone.utc)


def shopify_order(email="jordan.lee@example.com", name="#1001", paid=True, placed=None, updated=None,
                  first="Jordan", last="Lee", lines=None, order_id=None, refunds=None, fulfillments=None,
                  fulfillment_status=None, financial_status=None, cancelled_at=None):
    placed = placed or now() - timedelta(minutes=5)
    updated = updated or placed
    lines = lines or [{"sku": "CNDL-CEDAR-8", "title": "Cedar & Smoke candle, 8 oz", "quantity": 2, "price": "24.00"}]
    subtotal = sum(float(li["price"]) * li["quantity"] for li in lines)
    total = round(subtotal * 1.09, 2)
    return {
        "id": order_id or next(_ids),
        "name": name,
        "order_number": int(name.strip("#")),
        "email": email,
        "created_at": iso(placed),
        "processed_at": iso(placed),
        "updated_at": iso(updated),
        "cancelled_at": cancelled_at,
        "currency": "USD",
        "subtotal_price": f"{subtotal:.2f}",
        "total_price": f"{total:.2f}",
        "financial_status": financial_status or ("paid" if paid else "pending"),
        "fulfillment_status": fulfillment_status,
        "customer": {"id": next(_ids), "email": email, "first_name": first, "last_name": last, "phone": None},
        "line_items": [{"id": next(_ids), **li} for li in lines],
        "refunds": refunds or [],
        "fulfillments": fulfillments or [],
    }


def shopify_refund(order_id, amount="10.00", refund_id=None):
    return {
        "id": refund_id or next(_ids),
        "order_id": order_id,
        "created_at": iso(now()),
        "processed_at": iso(now()),
        "transactions": [{"id": next(_ids), "kind": "refund", "status": "success", "amount": amount}],
    }


def shopify_fulfillment(order_id, status="success", tracking="1Z999AA10123456784", fulfillment_id=None):
    return {
        "id": fulfillment_id or next(_ids),
        "order_id": order_id,
        "status": status,
        "tracking_company": "UPS",
        "tracking_number": tracking,
        "tracking_numbers": [tracking] if tracking else [],
        "tracking_url": f"https://www.ups.com/track?tracknum={tracking}" if tracking else None,
        "shipment_status": None,
        "created_at": iso(now()),
        "updated_at": iso(now()),
    }


def stripe_event(kind, obj, event_id=None, created=None):
    return {
        "id": event_id or f"evt_test_{next(_ids)}",
        "object": "event",
        "type": kind,
        "created": int((created or now()).timestamp()),
        "data": {"object": obj},
        "livemode": False,
    }


def stripe_invoice(email="jordan.lee@example.com", name="Jordan Lee", invoice_id=None, number="WHL-0001",
                   payment_intent=None, amount=38400):
    return {
        "id": invoice_id or f"in_test_{next(_ids)}",
        "object": "invoice",
        "number": number,
        "customer": "cus_test_1",
        "customer_email": email,
        "customer_name": name,
        "currency": "usd",
        "subtotal": amount,
        "total": amount,
        "amount_paid": amount,
        "created": int((now() - timedelta(days=1)).timestamp()),
        "status": "paid",
        "status_transitions": {"paid_at": int(now().timestamp())},
        **({"payment_intent": payment_intent} if payment_intent else {}),
        "lines": {"data": [{"id": f"il_test_{next(_ids)}", "description": "Cedar & Smoke candle, 8 oz (case of 24)",
                            "quantity": 2, "amount": amount, "metadata": {"sku": "CNDL-CEDAR-8-CS24"}}]},
    }


def stripe_invoice_payment(invoice_id, payment_intent):
    return {"id": f"inpay_test_{next(_ids)}", "object": "invoice_payment", "invoice": invoice_id,
            "payment": {"type": "payment_intent", "payment_intent": payment_intent}, "status": "paid"}


def stripe_charge_refunded(payment_intent, amount_refunded=9600, charge_id=None):
    return {"id": charge_id or f"ch_test_{next(_ids)}", "object": "charge", "payment_intent": payment_intent,
            "amount_refunded": amount_refunded, "currency": "usd", "refunded": False}

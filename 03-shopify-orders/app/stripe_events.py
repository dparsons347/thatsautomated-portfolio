"""Stripe events for the wholesale channel: wholesale buyers are invoiced in Stripe, and a paid
invoice is a wholesale order."""
from datetime import datetime, timezone

from . import store

HANDLED = {"invoice.paid", "invoice_payment.paid", "charge.refunded"}


def _ts(unix) -> str | None:
    return datetime.fromtimestamp(int(unix), tz=timezone.utc).isoformat() if unix else None


def handle(conn, event: dict) -> tuple[str, str]:
    kind = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    if kind == "invoice.paid":
        return apply_invoice_paid(conn, obj, event)
    if kind == "invoice_payment.paid":
        return apply_invoice_payment(conn, obj)
    if kind == "charge.refunded":
        return apply_charge_refunded(conn, obj, event)
    return "ignored", f"event {kind} is not used"


def _payment_intent_from_invoice(inv: dict) -> str | None:
    """Older API versions put payment_intent on the invoice. From 2025-03-31 it moved to
    invoice.payments (and the invoice_payment.paid event), which is handled separately."""
    pi = inv.get("payment_intent")
    if isinstance(pi, dict):
        pi = pi.get("id")
    if pi:
        return pi
    for p in ((inv.get("payments") or {}).get("data") or []):
        pay = p.get("payment") or {}
        if pay.get("payment_intent"):
            v = pay["payment_intent"]
            return v.get("id") if isinstance(v, dict) else v
    return None


def _line_sku(line: dict) -> str | None:
    meta = line.get("metadata") or {}
    if meta.get("sku"):
        return meta["sku"]
    price = line.get("price") or {}
    return (price.get("metadata") or {}).get("sku") if isinstance(price, dict) else None


def apply_invoice_paid(conn, inv: dict, event: dict) -> tuple[str, str]:
    wholesale = store.channel(conn, "wholesale")
    paid_at = _ts((inv.get("status_transitions") or {}).get("paid_at")) or _ts(event.get("created"))
    customer_id = store.upsert_customer(conn, inv.get("customer_email"), *_split_name(inv.get("customer_name")),
                                        inv.get("customer_phone"))
    order_id, _ = store.upsert_order(
        conn,
        channel_id=wholesale["id"],
        external_id=inv["id"],
        order_number=inv.get("number") or inv["id"],
        customer_id=customer_id,
        currency=(inv.get("currency") or "usd").upper(),
        subtotal=store.cents(inv.get("subtotal")),
        total=store.cents(inv.get("total")),
        financial_status="paid",
        fulfillment_status="unfulfilled",
        placed_at=_ts(inv.get("created")),
        paid_at=paid_at,
        cancelled_at=None,
        source_updated_at=None,
        raw=inv,
    )
    lines = []
    for ln in ((inv.get("lines") or {}).get("data") or []):
        qty = int(ln.get("quantity") or 1)
        lines.append({
            "external_id": ln["id"],
            "sku": _line_sku(ln),
            "title": ln.get("description") or "",
            "quantity": qty,
            "unit_price": store.money(store.cents(ln.get("amount")) / qty),
        })
    store.replace_lines(conn, order_id, lines)
    conn.execute(
        """INSERT INTO payments (order_id, provider, external_id, payment_intent, amount, currency, paid_at)
           VALUES (%s, 'stripe', %s, %s, %s, %s, %s)
           ON CONFLICT (provider, external_id) DO UPDATE
               SET payment_intent = coalesce(payments.payment_intent, EXCLUDED.payment_intent)""",
        (order_id, inv["id"], _payment_intent_from_invoice(inv), store.cents(inv.get("amount_paid")),
         (inv.get("currency") or "usd").upper(), paid_at),
    )
    return "applied", f"wholesale invoice {inv.get('number') or inv['id']} paid, {store.cents(inv.get('amount_paid'))}"


def _split_name(name: str | None) -> tuple[str | None, str | None]:
    if not name:
        return None, None
    first, _, last = name.strip().partition(" ")
    return first or None, last or None


def apply_invoice_payment(conn, ip: dict) -> tuple[str, str]:
    """invoice_payment.paid links the PaymentIntent to the invoice on newer API versions,
    which is what lets a later refund find its order."""
    invoice_id = ip.get("invoice")
    pay = ip.get("payment") or {}
    pi = pay.get("payment_intent")
    if isinstance(pi, dict):
        pi = pi.get("id")
    if not invoice_id or not pi:
        return "ignored", "invoice payment without an invoice or payment intent"
    row = conn.execute(
        "UPDATE payments SET payment_intent = %s WHERE provider = 'stripe' AND external_id = %s RETURNING id",
        (pi, invoice_id),
    ).fetchone()
    if row is None:
        raise store.Deferred(f"invoice payment for {invoice_id} arrived before invoice.paid")
    return "applied", f"linked {pi} to {invoice_id}"


def apply_charge_refunded(conn, ch: dict, event: dict) -> tuple[str, str]:
    pi = ch.get("payment_intent")
    if isinstance(pi, dict):
        pi = pi.get("id")
    payment = conn.execute("SELECT * FROM payments WHERE payment_intent = %s", (pi,)).fetchone() if pi else None
    if payment is None:
        # Not a wholesale invoice payment we know about. Worth a human look, not a retry loop.
        store.queue(conn, "unmatched_refund", f"unmatched_refund:{ch.get('id')}", None, {
            "kind": "unmatched_refund",
            "charge": ch.get("id"),
            "payment_intent": pi,
            "amount_refunded": str(store.cents(ch.get("amount_refunded"))),
        })
        return "unmatched", f"refund on {ch.get('id')} has no matching wholesale payment"
    store.upsert_refund(conn, payment["order_id"], "stripe", ch["id"], store.cents(ch.get("amount_refunded")),
                        _ts(event.get("created")))
    return "applied", f"refund {store.cents(ch.get('amount_refunded'))} on {payment['external_id']}"

"""Database writes shared by the Shopify and Stripe handlers. Every function takes an open
connection inside a transaction, so one webhook is applied completely or not at all."""
from decimal import Decimal, ROUND_HALF_UP

from psycopg.types.json import Jsonb


class Deferred(Exception):
    """The webhook refers to something we haven't seen yet (a refund before its order).
    The whole transaction is rolled back and the sender gets a 503, so it retries later."""


def normalize_email(email: str | None) -> str | None:
    """Trim and lowercase. Plus-aliases and Gmail dots are left alone on purpose: a merchant
    can't know they're the same person, and merging two real people is worse than a duplicate."""
    if not email:
        return None
    email = email.strip().lower()
    return email if "@" in email else None


def money(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cents(value) -> Decimal:
    return (Decimal(int(value or 0)) / 100).quantize(Decimal("0.01"))


def channel(conn, code: str) -> dict:
    row = conn.execute("SELECT * FROM channels WHERE code = %s", (code,)).fetchone()
    if row is None:
        raise RuntimeError(f"channel {code} is not configured")
    return row


# --- webhook log -------------------------------------------------------------------------

def claim_event(conn, source: str, event_key: str, topic: str, channel_id: int | None, payload: dict) -> bool:
    """Record the delivery. Returns False if this exact event was already accepted (a replay).

    The unique index does the work: two copies arriving at the same moment serialize on it,
    and the second one sees the first as a replay once it commits."""
    row = conn.execute(
        """INSERT INTO webhook_events (source, event_key, topic, channel_id, outcome, payload)
           VALUES (%s, %s, %s, %s, 'received', %s)
           ON CONFLICT (source, event_key) DO UPDATE
               SET replays = webhook_events.replays + 1, last_replay_at = now()
           RETURNING (xmax = 0) AS inserted""",
        (source, event_key, topic, channel_id, Jsonb(payload)),
    ).fetchone()
    return bool(row["inserted"])


def finish_event(conn, source: str, event_key: str, outcome: str, detail: str | None = None) -> None:
    conn.execute(
        "UPDATE webhook_events SET outcome = %s, detail = %s WHERE source = %s AND event_key = %s",
        (outcome, detail, source, event_key),
    )


def reject(conn, source: str, reason: str, remote_addr: str | None, headers: dict, body: bytes) -> None:
    import hashlib

    keep = {k: v for k, v in headers.items() if k.lower().startswith(("x-shopify", "stripe", "user-agent", "content-type"))}
    conn.execute(
        """INSERT INTO rejected_requests (source, reason, remote_addr, headers, body_sha256, body_excerpt)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (source, reason, remote_addr, Jsonb(keep), hashlib.sha256(body).hexdigest(), body[:500].decode("utf-8", "replace")),
    )


# --- customers and orders ------------------------------------------------------------------

def upsert_customer(conn, email, first_name=None, last_name=None, phone=None) -> int | None:
    email = normalize_email(email)
    if email is None:
        return None
    row = conn.execute(
        """INSERT INTO customers (email, first_name, last_name, phone) VALUES (%s, %s, %s, %s)
           ON CONFLICT (email) DO UPDATE SET
               first_name = coalesce(EXCLUDED.first_name, customers.first_name),
               last_name  = coalesce(EXCLUDED.last_name,  customers.last_name),
               phone      = coalesce(EXCLUDED.phone,      customers.phone),
               updated_at = now()
           RETURNING id""",
        (email, first_name or None, last_name or None, phone or None),
    ).fetchone()
    return row["id"]


def upsert_order(conn, *, channel_id, external_id, order_number, customer_id, currency, subtotal, total,
                 financial_status, fulfillment_status, placed_at, paid_at, cancelled_at, source_updated_at,
                 raw) -> tuple[int, bool]:
    """Insert or update one order. Returns (order id, applied). applied is False when the stored
    copy is newer than this payload (webhooks can arrive out of order), in which case nothing changes."""
    row = conn.execute(
        """INSERT INTO orders (channel_id, external_id, order_number, customer_id, currency, subtotal, total,
                               financial_status, fulfillment_status, placed_at, paid_at, cancelled_at,
                               source_updated_at, raw)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (channel_id, external_id) DO UPDATE SET
               order_number       = EXCLUDED.order_number,
               customer_id        = coalesce(EXCLUDED.customer_id, orders.customer_id),
               currency           = EXCLUDED.currency,
               subtotal           = EXCLUDED.subtotal,
               total              = EXCLUDED.total,
               financial_status   = EXCLUDED.financial_status,
               fulfillment_status = EXCLUDED.fulfillment_status,
               paid_at            = coalesce(orders.paid_at, EXCLUDED.paid_at),
               cancelled_at       = EXCLUDED.cancelled_at,
               source_updated_at  = EXCLUDED.source_updated_at,
               raw                = EXCLUDED.raw,
               updated_at         = now()
           WHERE orders.source_updated_at IS NULL
              OR EXCLUDED.source_updated_at IS NULL
              OR EXCLUDED.source_updated_at >= orders.source_updated_at
           RETURNING id""",
        (channel_id, external_id, order_number, customer_id, currency, subtotal, total, financial_status,
         fulfillment_status, placed_at, paid_at, cancelled_at, source_updated_at, Jsonb(raw)),
    ).fetchone()
    if row is not None:
        return row["id"], True
    existing = conn.execute(
        "SELECT id FROM orders WHERE channel_id = %s AND external_id = %s", (channel_id, external_id)
    ).fetchone()
    return existing["id"], False


def replace_lines(conn, order_id: int, lines: list[dict]) -> None:
    conn.execute("DELETE FROM order_lines WHERE order_id = %s", (order_id,))
    for ln in lines:
        conn.execute(
            """INSERT INTO order_lines (order_id, external_id, sku, title, quantity, unit_price)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (order_id, ln["external_id"], ln.get("sku") or None, ln["title"], ln["quantity"], ln["unit_price"]),
        )


def find_order(conn, channel_id: int, external_id: str) -> dict | None:
    return conn.execute(
        "SELECT * FROM orders WHERE channel_id = %s AND external_id = %s", (channel_id, str(external_id))
    ).fetchone()


# --- refunds -----------------------------------------------------------------------------

def upsert_refund(conn, order_id: int, source: str, external_id: str, amount, refunded_at) -> None:
    """Keyed on the provider's ID. For Stripe the key is the charge and the amount is the
    running total Stripe reports, so it only ever grows."""
    conn.execute(
        """INSERT INTO refunds (order_id, source, external_id, amount, refunded_at)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (source, external_id) DO UPDATE SET amount = greatest(refunds.amount, EXCLUDED.amount)""",
        (order_id, source, str(external_id), amount, refunded_at),
    )
    conn.execute(
        """UPDATE orders SET total_refunded = (SELECT coalesce(sum(amount), 0) FROM refunds WHERE order_id = %s),
                             updated_at = now()
           WHERE id = %s""",
        (order_id, order_id),
    )


# --- fulfillments and notifications --------------------------------------------------------

def upsert_fulfillment(conn, order: dict, channel_row: dict, f: dict) -> None:
    """Record a fulfillment. The first successful one marks the order fulfilled, clears a stuck
    flag, and queues exactly one shipped email for that fulfillment."""
    conn.execute(
        """INSERT INTO fulfillments (order_id, external_id, status, shipment_status, tracking_company,
                                     tracking_number, tracking_url)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (order_id, external_id) DO UPDATE SET
               status = EXCLUDED.status,
               shipment_status = coalesce(EXCLUDED.shipment_status, fulfillments.shipment_status),
               tracking_company = coalesce(EXCLUDED.tracking_company, fulfillments.tracking_company),
               tracking_number = coalesce(EXCLUDED.tracking_number, fulfillments.tracking_number),
               tracking_url = coalesce(EXCLUDED.tracking_url, fulfillments.tracking_url),
               updated_at = now()""",
        (order["id"], str(f["external_id"]), f["status"], f.get("shipment_status"), f.get("tracking_company"),
         f.get("tracking_number"), f.get("tracking_url")),
    )
    if f["status"] != "success":
        return
    conn.execute(
        "UPDATE orders SET fulfilled_at = coalesce(fulfilled_at, now()), updated_at = now() WHERE id = %s",
        (order["id"],),
    )
    queue_customer_notice(conn, "shipped", f"shipped:{channel_row['code']}:{f['external_id']}", order, channel_row, {
        "tracking_company": f.get("tracking_company"),
        "tracking_number": f.get("tracking_number"),
        "tracking_url": f.get("tracking_url"),
    })


def queue_customer_notice(conn, kind: str, dedupe_key: str, order: dict, channel_row: dict, extra: dict) -> bool:
    customer = None
    if order.get("customer_id"):
        customer = conn.execute("SELECT * FROM customers WHERE id = %s", (order["customer_id"],)).fetchone()
    if customer is None:
        return False  # nobody to email; the unified view still shows the order
    payload = {
        "kind": kind,
        "to_email": customer["email"],
        "first_name": customer["first_name"],
        "order_number": order["order_number"],
        "store": channel_row["name"],
        **extra,
    }
    return queue(conn, kind, dedupe_key, order["id"], payload)


def queue(conn, kind: str, dedupe_key: str, order_id: int | None, payload: dict) -> bool:
    """Returns True if queued, False if this notice was already queued before."""
    row = conn.execute(
        """INSERT INTO notifications (kind, dedupe_key, order_id, payload) VALUES (%s, %s, %s, %s)
           ON CONFLICT (dedupe_key) DO NOTHING RETURNING id""",
        (kind, dedupe_key, order_id, Jsonb(payload)),
    ).fetchone()
    return row is not None

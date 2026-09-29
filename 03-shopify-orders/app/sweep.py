"""Finds paid orders that never got a fulfillment. Webhooks tell us what happened; only a sweep
can notice what didn't."""
import logging

from . import store

log = logging.getLogger("orders.sweep")


def run(conn, stuck_after_minutes: int) -> list[dict]:
    """Mark overdue orders stuck and queue one team alert and one customer delay notice for each.
    Returns the orders it marked. Running it twice marks nothing new the second time."""
    # Only one sweep at a time, even with two containers.
    got = conn.execute("SELECT pg_try_advisory_xact_lock(3004) AS ok").fetchone()["ok"]
    if not got:
        return []
    stuck = conn.execute(
        """UPDATE orders o SET stuck_at = now(), updated_at = now()
           FROM channels ch
           WHERE ch.id = o.channel_id
             AND ch.sweep_enabled
             AND o.paid_at IS NOT NULL
             AND o.paid_at < now() - make_interval(mins => %s)
             AND o.fulfilled_at IS NULL
             AND o.cancelled_at IS NULL
             AND o.stuck_at IS NULL
             AND o.total_refunded < o.total
             AND NOT EXISTS (SELECT 1 FROM fulfillments f WHERE f.order_id = o.id AND f.status = 'success')
           RETURNING o.*, ch.code AS channel_code, ch.name AS channel_name""",
        (stuck_after_minutes,),
    ).fetchall()
    for o in stuck:
        channel_row = {"code": o["channel_code"], "name": o["channel_name"]}
        hours = round(stuck_after_minutes / 60, 1)
        store.queue(conn, "stuck_alert", f"stuck:{o['id']}", o["id"], {
            "kind": "stuck_alert",
            "store": o["channel_name"],
            "order_number": o["order_number"],
            "total": str(o["total"]),
            "paid_at": o["paid_at"].isoformat(),
            "threshold_hours": hours,
        })
        store.queue_customer_notice(conn, "delayed", f"delayed:{o['id']}", o, channel_row, {})
        log.warning("stuck order %s on %s, paid %s", o["order_number"], o["channel_name"], o["paid_at"])
    return stuck

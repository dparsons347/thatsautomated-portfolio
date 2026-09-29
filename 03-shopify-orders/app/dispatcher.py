"""Delivers the notifications outbox to n8n. n8n owns the wording and the channel (email, Slack);
this owns making sure every notice gets there exactly once from our side."""
import logging
from datetime import timedelta

import httpx

log = logging.getLogger("orders.dispatch")


def backoff(attempts: int) -> timedelta:
    """1, 2, 4, 8 ... minutes, capped at an hour."""
    return timedelta(minutes=min(60, 2 ** max(0, attempts - 1)))


def run(conn, url: str, key: str, max_attempts: int, client: httpx.Client | None = None, batch: int = 20) -> dict:
    """Send what's due. Rows are locked with SKIP LOCKED so two dispatchers never send the same row."""
    if not url:
        return {"sent": 0, "retry": 0, "failed": 0, "skipped": "N8N_NOTIFY_URL not set"}
    rows = conn.execute(
        """SELECT * FROM notifications WHERE status = 'pending' AND next_attempt_at <= now()
           ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED""",
        (batch,),
    ).fetchall()
    own = client is None
    client = client or httpx.Client(timeout=10)
    counts = {"sent": 0, "retry": 0, "failed": 0}
    try:
        for n in rows:
            error = None
            try:
                r = client.post(url, json={"id": n["id"], **n["payload"]}, headers={"X-Webhook-Key": key})
                if r.status_code >= 300:
                    error = f"n8n answered {r.status_code}: {r.text[:200]}"
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"
            attempts = n["attempts"] + 1
            if error is None:
                conn.execute("UPDATE notifications SET status = 'sent', attempts = %s, sent_at = now(), last_error = NULL WHERE id = %s",
                             (attempts, n["id"]))
                counts["sent"] += 1
            elif attempts >= max_attempts:
                conn.execute("UPDATE notifications SET status = 'failed', attempts = %s, last_error = %s WHERE id = %s",
                             (attempts, error, n["id"]))
                counts["failed"] += 1
                log.error("notification %s (%s) gave up after %s attempts: %s", n["id"], n["kind"], attempts, error)
            else:
                conn.execute("UPDATE notifications SET attempts = %s, last_error = %s, next_attempt_at = now() + %s WHERE id = %s",
                             (attempts, error, backoff(attempts), n["id"]))
                counts["retry"] += 1
                log.warning("notification %s (%s) attempt %s failed, will retry: %s", n["id"], n["kind"], attempts, error)
    finally:
        if own:
            client.close()
    return counts

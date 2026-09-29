"""Webhook receiver for two Shopify stores and Stripe (wholesale), writing to one Postgres schema."""
import json
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import config, db, dispatcher, shopify, store, stripe_events, sweep
from .signatures import SignatureError, verify_shopify, verify_stripe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("orders")


def _loop(stop: threading.Event, every: int, name: str, fn) -> None:
    while not stop.wait(every):
        try:
            fn()
        except Exception:  # keep the loop alive; the error is in the log and /health shows the backlog
            log.exception("%s run failed", name)


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.load()
    stop = threading.Event()

    def run_sweep():
        with db.transaction() as conn:
            return sweep.run(conn, settings.stuck_after_minutes)

    def run_dispatch():
        with db.transaction() as conn:
            return dispatcher.run(conn, settings.n8n_notify_url, settings.n8n_notify_key, settings.dispatch_max_attempts)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_pool(settings.database_url)
        with db.transaction() as conn:
            applied = db.migrate(conn)
            db.sync_channels(conn, settings)
        if applied:
            log.info("applied migrations: %s", ", ".join(applied))
        threads = []
        if settings.run_background:
            for name, every, fn in (("sweep", settings.sweep_every_seconds, run_sweep),
                                    ("dispatch", settings.dispatch_every_seconds, run_dispatch)):
                t = threading.Thread(target=_loop, args=(stop, every, name, fn), name=name, daemon=True)
                t.start()
                threads.append(t)
        yield
        stop.set()
        for t in threads:
            t.join(timeout=5)
        db.close_pool()

    app = FastAPI(title="Orders source of truth", lifespan=lifespan)

    def _reject(source: str, reason: str, request: Request, body: bytes, status: int) -> JSONResponse:
        with db.transaction() as conn:
            store.reject(conn, source, reason, request.client.host if request.client else None,
                         dict(request.headers), body)
        log.warning("%s webhook REJECTED from %s: %s", source, request.client.host if request.client else "?", reason)
        return JSONResponse({"error": reason}, status_code=status)

    def _apply(source: str, key: str, topic: str, channel_id, payload: dict, handler) -> JSONResponse:
        try:
            with db.transaction() as conn:
                if not store.claim_event(conn, source, key, topic, channel_id, payload):
                    log.info("%s %s %s -> replay, ignored", source, topic, key)
                    return JSONResponse({"result": "replay"})
                outcome, detail = handler(conn)
                store.finish_event(conn, source, key, outcome, detail)
        except store.Deferred as exc:
            # Rolled back, including the event row, so the retry is treated as new.
            log.warning("%s %s %s -> deferred: %s", source, topic, key, exc)
            return JSONResponse({"result": "deferred", "detail": str(exc)}, status_code=503)
        log.info("%s %s %s -> %s: %s", source, topic, key, outcome, detail)
        return JSONResponse({"result": outcome, "detail": detail})

    @app.post("/webhooks/shopify")
    async def shopify_webhook(request: Request):
        body = await request.body()
        h = request.headers
        shop_domain = (h.get("x-shopify-shop-domain") or "").strip().lower()
        topic = h.get("x-shopify-topic") or ""
        cfg = settings.store_for_domain(shop_domain)
        if cfg is None:
            return await run_in_threadpool(_reject, "shopify", f"unknown shop {shop_domain or '(none)'}", request, body, 401)
        try:
            verify_shopify(body, h.get("x-shopify-hmac-sha256"), cfg.secret)
        except SignatureError as exc:
            return await run_in_threadpool(_reject, "shopify", str(exc), request, body, 401)
        key = shopify.event_key(shop_domain, topic, h)
        try:
            payload = json.loads(body)
        except ValueError:
            return await run_in_threadpool(_reject, "shopify", "body is not JSON", request, body, 400)
        if not key or not isinstance(payload, dict):
            return await run_in_threadpool(_reject, "shopify", "no event ID header or bad payload", request, body, 400)

        def work():
            with db.transaction() as conn:
                ch = store.channel(conn, cfg.code)
            return _apply("shopify", key, topic, ch["id"], payload, lambda conn: shopify.handle(conn, ch, topic, payload))

        return await run_in_threadpool(work)

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request):
        body = await request.body()
        try:
            verify_stripe(body, request.headers.get("stripe-signature"), settings.stripe_webhook_secret,
                          settings.stripe_tolerance_seconds)
        except SignatureError as exc:
            return await run_in_threadpool(_reject, "stripe", str(exc), request, body, 401)
        try:
            event = json.loads(body)
            event_id, kind = event["id"], event["type"]
        except (ValueError, KeyError, TypeError):
            return await run_in_threadpool(_reject, "stripe", "body is not a Stripe event", request, body, 400)

        def work():
            return _apply("stripe", event_id, kind, None, event, lambda conn: stripe_events.handle(conn, event))

        return await run_in_threadpool(work)

    def _admin(authorization: str | None) -> None:
        if not settings.admin_token or authorization != f"Bearer {settings.admin_token}":
            raise HTTPException(status_code=401, detail="admin token required")

    @app.post("/admin/sweep")
    async def admin_sweep(authorization: str | None = Header(default=None)):
        _admin(authorization)
        stuck = await run_in_threadpool(run_sweep)
        return {"marked_stuck": [{"order": o["order_number"], "store": o["channel_name"]} for o in stuck]}

    @app.post("/admin/dispatch")
    async def admin_dispatch(authorization: str | None = Header(default=None)):
        _admin(authorization)
        return await run_in_threadpool(run_dispatch)

    @app.get("/health")
    async def health():
        def check():
            with db.transaction() as conn:
                return conn.execute(
                    """SELECT
                         (SELECT count(*) FROM notifications WHERE status = 'pending') AS pending,
                         (SELECT count(*) FROM notifications WHERE status = 'failed') AS failed,
                         (SELECT extract(epoch FROM now() - min(created_at))::int FROM notifications WHERE status = 'pending') AS oldest_pending_seconds,
                         (SELECT count(*) FROM orders WHERE stuck_at IS NOT NULL AND fulfilled_at IS NULL) AS stuck_orders"""
                ).fetchone()
        stats = await run_in_threadpool(check)
        healthy = stats["failed"] == 0 and (stats["oldest_pending_seconds"] or 0) < 3600
        return JSONResponse({"ok": healthy, **stats}, status_code=200 if healthy else 503)

    return app


# Run with: uvicorn --factory app.main:create_app

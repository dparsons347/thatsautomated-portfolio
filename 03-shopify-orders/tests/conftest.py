import itertools
import json
import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import create_app
from app.signatures import sign_shopify, sign_stripe

ADMIN = "test-admin-token"
STRIPE_SECRET = "whsec_test_secret"
STORES = (
    config.ShopifyStore("shopify_a", "Store A", "store-a.myshopify.com", "shpss_store_a_secret"),
    config.ShopifyStore("shopify_b", "Store B", "store-b.myshopify.com", "shpss_store_b_secret"),
)
ADMIN_URL = os.environ.get("TEST_ADMIN_DATABASE_URL", "postgresql://postgres@localhost:5433/postgres?host=/tmp")
TEST_DB = "orders_test"


def _test_url() -> str:
    return ADMIN_URL.replace("/postgres?", f"/{TEST_DB}?")


@pytest.fixture(scope="session")
def settings():
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    return config.Settings(
        database_url=_test_url(),
        shopify_stores=STORES,
        stripe_webhook_secret=STRIPE_SECRET,
        wholesale_name="Wholesale",
        admin_token=ADMIN,
        stuck_after_minutes=60,
        n8n_notify_url="http://n8n.test/webhook/p3-order-notifications",
        n8n_notify_key="test-key",
        run_background=False,
    )


@pytest.fixture(scope="session")
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(autouse=True)
def clean(client):
    with db.transaction() as conn:
        conn.execute("""TRUNCATE notifications, webhook_events, rejected_requests, fulfillments, refunds,
                        payments, order_lines, orders, customers RESTART IDENTITY CASCADE""")
    yield


@pytest.fixture
def sql():
    def run(query, params=None):
        with db.transaction() as conn:
            return conn.execute(query, params).fetchall()
    return run


_event_ids = itertools.count(1)


@pytest.fixture
def send_shopify(client):
    def send(topic, payload, store="a", event_id=None, secret=None, shop=None):
        cfg = STORES[0] if store == "a" else STORES[1]
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Topic": topic,
            "X-Shopify-Shop-Domain": shop or cfg.shop_domain,
            "X-Shopify-Hmac-Sha256": sign_shopify(body, secret or cfg.secret),
            "X-Shopify-Event-Id": str(event_id or f"evt-{next(_event_ids)}"),
            "X-Shopify-Webhook-Id": f"wh-{next(_event_ids)}",
        }
        return client.post("/webhooks/shopify", content=body, headers=headers)
    return send


@pytest.fixture
def send_stripe(client):
    def send(event, secret=STRIPE_SECRET, timestamp=None):
        body = json.dumps(event).encode()
        return client.post("/webhooks/stripe", content=body, headers={
            "Content-Type": "application/json",
            "Stripe-Signature": sign_stripe(body, secret, timestamp),
        })
    return send

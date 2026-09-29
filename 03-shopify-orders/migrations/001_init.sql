-- One source of truth for orders from two Shopify stores and a Stripe wholesale channel.

CREATE TABLE channels (
    id            serial PRIMARY KEY,
    code          text NOT NULL UNIQUE,            -- shopify_a, shopify_b, wholesale
    kind          text NOT NULL CHECK (kind IN ('shopify', 'stripe')),
    name          text NOT NULL,                   -- shown to customers and in the unified view
    shop_domain   text UNIQUE,                     -- Shopify only, e.g. store-a.myshopify.com
    sweep_enabled boolean NOT NULL DEFAULT true    -- is a missing fulfillment a problem on this channel?
);

CREATE TABLE customers (
    id          bigserial PRIMARY KEY,
    email       text NOT NULL UNIQUE,              -- normalized: trimmed, lowercased
    first_name  text,
    last_name   text,
    phone       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id                  bigserial PRIMARY KEY,
    channel_id          int NOT NULL REFERENCES channels(id),
    external_id         text NOT NULL,             -- Shopify order ID or Stripe invoice ID
    order_number        text,                      -- #1001 or the Stripe invoice number
    customer_id         bigint REFERENCES customers(id),
    currency            text NOT NULL,
    subtotal            numeric(12,2),
    total               numeric(12,2) NOT NULL,
    total_refunded      numeric(12,2) NOT NULL DEFAULT 0,
    financial_status    text,                      -- as the source reports it
    fulfillment_status  text,                      -- unfulfilled, partial, fulfilled
    placed_at           timestamptz NOT NULL,
    paid_at             timestamptz,
    fulfilled_at        timestamptz,
    cancelled_at        timestamptz,
    stuck_at            timestamptz,               -- set by the sweep, cleared by a fulfillment
    source_updated_at   timestamptz,               -- drops stale out-of-order updates
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    raw                 jsonb NOT NULL,
    UNIQUE (channel_id, external_id)
);
CREATE INDEX orders_customer_idx ON orders (customer_id);
CREATE INDEX orders_sweep_idx ON orders (paid_at) WHERE fulfilled_at IS NULL AND cancelled_at IS NULL AND stuck_at IS NULL;

CREATE TABLE order_lines (
    id           bigserial PRIMARY KEY,
    order_id     bigint NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    external_id  text NOT NULL,
    sku          text,
    title        text NOT NULL,
    quantity     int NOT NULL,
    unit_price   numeric(12,2) NOT NULL,
    UNIQUE (order_id, external_id)
);

CREATE TABLE payments (
    id              bigserial PRIMARY KEY,
    order_id        bigint NOT NULL REFERENCES orders(id),
    provider        text NOT NULL,                 -- stripe
    external_id     text NOT NULL,                 -- invoice ID (one payment per wholesale invoice)
    payment_intent  text,                          -- joins refunds back to the invoice
    amount          numeric(12,2) NOT NULL,
    currency        text NOT NULL,
    paid_at         timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, external_id)
);
CREATE UNIQUE INDEX payments_intent_idx ON payments (payment_intent) WHERE payment_intent IS NOT NULL;

CREATE TABLE refunds (
    id           bigserial PRIMARY KEY,
    order_id     bigint NOT NULL REFERENCES orders(id),
    source       text NOT NULL,                    -- shopify or stripe
    external_id  text NOT NULL,
    amount       numeric(12,2) NOT NULL,
    refunded_at  timestamptz NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, external_id)
);

CREATE TABLE fulfillments (
    id                bigserial PRIMARY KEY,
    order_id          bigint NOT NULL REFERENCES orders(id),
    external_id       text NOT NULL,
    status            text NOT NULL,               -- Shopify: pending, open, success, cancelled, error, failure
    shipment_status   text,
    tracking_company  text,
    tracking_number   text,
    tracking_url      text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (order_id, external_id)
);

-- Every accepted webhook. A second delivery with the same key is a replay and is not applied.
CREATE TABLE webhook_events (
    id           bigserial PRIMARY KEY,
    source       text NOT NULL,                    -- shopify or stripe
    event_key    text NOT NULL,                    -- X-Shopify-Event-Id or Stripe event ID
    topic        text NOT NULL,
    channel_id   int REFERENCES channels(id),
    received_at  timestamptz NOT NULL DEFAULT now(),
    replays      int NOT NULL DEFAULT 0,
    last_replay_at timestamptz,
    outcome      text NOT NULL,                    -- applied, ignored (topic we don't use), stale
    detail       text,
    payload      jsonb NOT NULL,
    UNIQUE (source, event_key)
);

-- Anything that failed verification. Logged, never applied.
CREATE TABLE rejected_requests (
    id           bigserial PRIMARY KEY,
    source       text NOT NULL,
    reason       text NOT NULL,
    remote_addr  text,
    headers      jsonb NOT NULL,
    body_sha256  text NOT NULL,
    body_excerpt text,
    received_at  timestamptz NOT NULL DEFAULT now()
);

-- Outbox for customer emails and team alerts. Written in the same transaction as the change
-- that caused it, delivered to n8n by the dispatcher, retried until n8n accepts it.
CREATE TABLE notifications (
    id               bigserial PRIMARY KEY,
    kind             text NOT NULL CHECK (kind IN ('shipped', 'delayed', 'stuck_alert', 'unmatched_refund')),
    dedupe_key       text NOT NULL UNIQUE,         -- one shipped email per fulfillment, one delay per order
    order_id         bigint REFERENCES orders(id),
    payload          jsonb NOT NULL,
    status           text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    attempts         int NOT NULL DEFAULT 0,
    next_attempt_at  timestamptz NOT NULL DEFAULT now(),
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    sent_at          timestamptz
);
CREATE INDEX notifications_due_idx ON notifications (next_attempt_at) WHERE status = 'pending';

-- The "one place" table.
CREATE VIEW orders_unified AS
SELECT
    o.id,
    ch.name                                   AS channel,
    o.order_number,
    c.email                                   AS customer_email,
    concat_ws(' ', c.first_name, c.last_name) AS customer_name,
    (SELECT count(*) FROM orders o2 WHERE o2.customer_id = o.customer_id) AS customer_orders,
    o.total,
    o.total_refunded,
    o.currency,
    CASE
        WHEN o.cancelled_at IS NOT NULL THEN 'cancelled'
        WHEN o.total_refunded >= o.total AND o.total > 0 THEN 'refunded'
        WHEN o.fulfilled_at IS NOT NULL THEN 'fulfilled'
        WHEN o.stuck_at IS NOT NULL THEN 'STUCK'
        WHEN o.paid_at IS NOT NULL THEN 'paid, awaiting fulfillment'
        ELSE coalesce(o.financial_status, 'open')
    END                                       AS status,
    (SELECT f.tracking_number FROM fulfillments f WHERE f.order_id = o.id ORDER BY f.created_at DESC LIMIT 1) AS tracking,
    o.placed_at,
    o.paid_at,
    o.fulfilled_at
FROM orders o
JOIN channels ch ON ch.id = o.channel_id
LEFT JOIN customers c ON c.id = o.customer_id
ORDER BY o.placed_at DESC;

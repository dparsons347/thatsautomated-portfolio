"""Settings from environment variables. See deploy/.env.example for the full list."""
import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ShopifyStore:
    code: str          # channel code, e.g. shopify_a
    name: str          # shown in the unified view and in customer emails
    shop_domain: str   # store-a.myshopify.com
    secret: str        # the key Shopify signs this store's webhooks with


@dataclass(frozen=True)
class Settings:
    database_url: str
    shopify_stores: tuple[ShopifyStore, ...]
    stripe_webhook_secret: str
    wholesale_name: str = "Wholesale"
    stripe_tolerance_seconds: int = 300
    n8n_notify_url: str = ""
    n8n_notify_key: str = ""
    admin_token: str = ""
    stuck_after_minutes: int = 24 * 60
    sweep_every_seconds: int = 15 * 60
    dispatch_every_seconds: int = 30
    dispatch_max_attempts: int = 10
    run_background: bool = True

    def store_for_domain(self, domain: str) -> ShopifyStore | None:
        domain = (domain or "").strip().lower()
        for s in self.shopify_stores:
            if s.shop_domain == domain:
                return s
        return None


def _stores_from_env() -> tuple[ShopifyStore, ...]:
    """SHOPIFY_STORES is JSON: [{"code": "shopify_a", "name": "...", "shop_domain": "...", "secret": "..."}]"""
    raw = os.environ.get("SHOPIFY_STORES", "[]")
    return tuple(
        ShopifyStore(
            code=s["code"],
            name=s["name"],
            shop_domain=s["shop_domain"].strip().lower(),
            secret=s["secret"],
        )
        for s in json.loads(raw)
    )


def load() -> Settings:
    e = os.environ
    return Settings(
        database_url=e["DATABASE_URL"],
        shopify_stores=_stores_from_env(),
        stripe_webhook_secret=e.get("STRIPE_WEBHOOK_SECRET", ""),
        wholesale_name=e.get("WHOLESALE_NAME", "Wholesale"),
        stripe_tolerance_seconds=int(e.get("STRIPE_TOLERANCE_SECONDS", "300")),
        n8n_notify_url=e.get("N8N_NOTIFY_URL", ""),
        n8n_notify_key=e.get("N8N_NOTIFY_KEY", ""),
        admin_token=e.get("ADMIN_TOKEN", ""),
        stuck_after_minutes=int(e.get("STUCK_AFTER_MINUTES", str(24 * 60))),
        sweep_every_seconds=int(e.get("SWEEP_EVERY_SECONDS", "900")),
        dispatch_every_seconds=int(e.get("DISPATCH_EVERY_SECONDS", "30")),
        dispatch_max_attempts=int(e.get("DISPATCH_MAX_ATTEMPTS", "10")),
        run_background=e.get("RUN_BACKGROUND", "1") == "1",
    )

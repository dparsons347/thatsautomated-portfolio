"""Connection pool and the migration runner."""
from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"

_pool: ConnectionPool | None = None


def init_pool(database_url: str) -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(database_url, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=True)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaction():
    """One connection, one transaction. Commits on success, rolls back on any exception."""
    assert _pool is not None, "init_pool() first"
    with _pool.connection() as conn:
        with conn.transaction():
            yield conn


def migrate(conn) -> list[str]:
    """Apply migrations/*.sql in name order, once each. Safe to run on every start."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    conn.execute("SELECT pg_advisory_xact_lock(3003)")  # two containers starting at once
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        conn.execute(path.read_text())
        conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


def sync_channels(conn, settings) -> None:
    """Channels come from config so the store list lives in one place."""
    for s in settings.shopify_stores:
        conn.execute(
            """INSERT INTO channels (code, kind, name, shop_domain, sweep_enabled)
               VALUES (%s, 'shopify', %s, %s, true)
               ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, shop_domain = EXCLUDED.shop_domain""",
            (s.code, s.name, s.shop_domain),
        )
    # Wholesale orders ship on their own schedule (freight, pickups), so the sweep leaves them alone.
    conn.execute(
        """INSERT INTO channels (code, kind, name, sweep_enabled) VALUES ('wholesale', 'stripe', %s, false)
           ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name""",
        (settings.wholesale_name,),
    )

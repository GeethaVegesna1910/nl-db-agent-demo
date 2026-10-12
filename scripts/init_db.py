"""Create the database tables. Safe to re-run: existing tables are left alone."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re

from sqlalchemy import create_engine, text

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id  SERIAL PRIMARY KEY,
    first_name   VARCHAR(50)  NOT NULL,
    last_name    VARCHAR(50)  NOT NULL,
    email        VARCHAR(120) NOT NULL UNIQUE,
    city         VARCHAR(80)  NOT NULL,
    state        CHAR(2)      NOT NULL,
    country      VARCHAR(50)  NOT NULL DEFAULT 'USA',
    signup_date  DATE         NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id      SERIAL PRIMARY KEY,
    name            VARCHAR(120)   NOT NULL UNIQUE,
    category        VARCHAR(50)    NOT NULL,
    price           NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    cost            NUMERIC(10, 2) NOT NULL CHECK (cost >= 0),
    stock_quantity  INTEGER        NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id      SERIAL PRIMARY KEY,
    customer_id   INTEGER        NOT NULL REFERENCES customers (customer_id),
    order_date    TIMESTAMP      NOT NULL,
    status        VARCHAR(20)    NOT NULL
                  CHECK (status IN ('completed', 'pending', 'cancelled')),
    total_amount  NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0)
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id  SERIAL PRIMARY KEY,
    order_id       INTEGER        NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    product_id     INTEGER        NOT NULL REFERENCES products (product_id),
    quantity       INTEGER        NOT NULL CHECK (quantity > 0),
    unit_price     NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0)
);

CREATE INDEX IF NOT EXISTS idx_orders_customer_id      ON orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_date       ON orders (order_date);
CREATE INDEX IF NOT EXISTS idx_orders_status           ON orders (status);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id    ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id  ON order_items (product_id);

-- Chat memory (Phase 3). These two tables are private to the application:
-- the SQL validator blocks them, so the agent can never query chat history.
CREATE TABLE IF NOT EXISTS conversations (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT        NOT NULL DEFAULT 'demo',
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id               SERIAL PRIMARY KEY,
    conversation_id  INTEGER     NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role             TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT        NOT NULL,
    sql_used         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id     ON conversations (user_id, last_active_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id  ON messages (conversation_id, id);
"""

# The only tables the agent's login may read. conversations and messages are
# deliberately missing, so PostgreSQL itself refuses to show it chat history.
AGENT_READABLE_TABLES = ["customers", "products", "orders", "order_items"]


def create_agent_role(conn) -> None:
    """Create (or refresh) the read-only login that LLM-written SQL runs as."""
    role = settings.agent_db_user
    # A role name cannot be sent as a query parameter, so check it before
    # putting it into the SQL text.
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise ValueError("AGENT_DB_USER must be lowercase letters, digits and underscores")

    exists = conn.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).scalar()
    conn.execute(
        text("{} ROLE {} LOGIN PASSWORD :password".format("ALTER" if exists else "CREATE", role)),
        {"password": settings.agent_db_password},
    )
    # Start from nothing, then hand back only SELECT on the business tables.
    conn.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}".format(role)))
    conn.execute(text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}".format(role)))
    conn.execute(text("GRANT USAGE ON SCHEMA public TO {}".format(role)))
    conn.execute(text("GRANT SELECT ON {} TO {}".format(", ".join(AGENT_READABLE_TABLES), role)))
    # Extra belt: every transaction this role opens starts out read-only.
    conn.execute(text("ALTER ROLE {} SET default_transaction_read_only = on".format(role)))


def main() -> None:
    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        conn.execute(text(SCHEMA))
        create_agent_role(conn)
    print("Read-only role ready: {} (SELECT on {})".format(
        settings.agent_db_user, ", ".join(AGENT_READABLE_TABLES)
    ))
    print("Tables ready: customers, products, orders, order_items, conversations, messages")


if __name__ == "__main__":
    main()

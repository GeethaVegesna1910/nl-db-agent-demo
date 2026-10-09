"""Create the database tables. Safe to re-run: existing tables are left alone."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
"""


def main() -> None:
    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        conn.execute(text(SCHEMA))
    print("Tables ready: customers, products, orders, order_items")


if __name__ == "__main__":
    main()

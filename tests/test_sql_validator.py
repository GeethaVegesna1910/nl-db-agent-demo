import pytest

from app.security.sql_validator import sql_validator

ALLOWED = [
    "SELECT * FROM customers",
    "select count(*) from orders where status = 'completed';",
    "WITH t AS (SELECT customer_id, SUM(total_amount) AS spent FROM orders GROUP BY 1) "
    "SELECT * FROM t ORDER BY spent DESC LIMIT 10",
    "SELECT date_trunc('month', order_date) AS month, count(*) FROM orders GROUP BY 1",
    "SELECT replace(first_name, 'a', 'b') FROM customers",
    "SELECT name FROM products WHERE name LIKE '%Desk%'",
    "SELECT 'DROP TABLE customers' AS harmless_text",
    "SELECT 1 UNION SELECT 2",
    "-- top customers\nSELECT * FROM customers /* all of them */",
]

REJECTED = [
    "",
    "   ",
    "-- just a comment",
    "INSERT INTO customers (first_name) VALUES ('x')",
    "UPDATE orders SET status = 'cancelled'",
    "DELETE FROM orders",
    "DROP TABLE customers",
    "TRUNCATE orders",
    "ALTER TABLE orders ADD COLUMN x int",
    "CREATE TABLE t (id int)",
    "GRANT ALL ON orders TO public",
    "SELECT 1; DROP TABLE customers",
    "SELECT 1; SELECT 2",
    "/* hidden */ DROP TABLE customers",
    "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    "WITH u AS (UPDATE orders SET status = 'pending' RETURNING *) SELECT * FROM u",
    "SELECT * INTO orders_copy FROM orders",
    "SELECT * FROM orders FOR UPDATE",
    "EXPLAIN ANALYZE SELECT * FROM orders",
    "COPY customers TO '/tmp/customers.csv'",
    "SET statement_timeout = 0",
    "SELECT pg_sleep(60)",
    'SELECT "pg_sleep"(60)',
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT * FROM pg_catalog.pg_shadow",
    "SELECT * FROM information_schema.tables",
    "SELECT lo_import('/etc/passwd')",
    "SELECT set_config('statement_timeout', '0', false)",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_read_only_queries(sql):
    result = sql_validator.validate(sql)
    assert result.is_valid, result.error


@pytest.mark.parametrize("sql", REJECTED)
def test_rejects_unsafe_queries(sql):
    result = sql_validator.validate(sql)
    assert not result.is_valid
    assert result.error


def test_cleaned_sql_has_no_comments_or_trailing_semicolon():
    result = sql_validator.validate("SELECT 1 -- one\n;")
    assert result.sql == "SELECT 1"

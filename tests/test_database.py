"""Integration tests. They need the seeded database from Phase 1 to be running."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.database.connection import agent_engine, check_connection, engine
from app.database.executor import QueryExecutor, query_executor
from app.database.schema import schema_introspector
from app.security.sql_validator import ValidationResult

pytestmark = pytest.mark.skipif(not check_connection(), reason="database is not running")


class AllowEverything:
    """Stand-in validator, to prove the executor is safe even if validation is bypassed."""

    def validate(self, sql):
        return ValidationResult(is_valid=True, sql=sql)


def order_count():
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM orders")).scalar()


def test_schema_lists_the_four_tables():
    assert schema_introspector.get_table_names() == [
        "customers", "order_items", "orders", "products"
    ]


def test_schema_describes_columns_and_keys():
    orders = schema_introspector.get_table_schema("orders")
    assert [c["name"] for c in orders["columns"]] == [
        "order_id", "customer_id", "order_date", "status", "total_amount"
    ]
    assert orders["primary_key"] == ["order_id"]
    assert orders["foreign_keys"][0]["referred_table"] == "customers"
    assert "references customers(customer_id)" in schema_introspector.describe()


def test_schema_unknown_table_raises():
    with pytest.raises(KeyError):
        schema_introspector.get_table_schema("nope")


def test_executes_select():
    result = query_executor.execute("SELECT count(*) AS n FROM products")
    assert result.success
    assert result.columns == ["n"]
    assert result.rows == [[24]]
    assert result.row_count == 1
    assert not result.truncated


def test_handles_percent_and_colon_in_sql():
    result = query_executor.execute(
        "SELECT name, price::text FROM products WHERE name LIKE '%Desk%' ORDER BY name"
    )
    assert result.success, result.error
    assert [r[0] for r in result.rows] == ["LED Desk Lamp", "Standing Desk"]


def test_row_limit_truncates():
    result = QueryExecutor(max_rows=10).execute("SELECT * FROM orders")
    assert result.success
    assert result.row_count == 10
    assert result.truncated


def test_validation_failure_is_not_executed():
    before = order_count()
    result = query_executor.execute("DELETE FROM orders")
    assert not result.success
    assert result.error_type == "validation"
    assert order_count() == before


def test_database_error_is_reported():
    result = query_executor.execute("SELECT no_such_column FROM orders")
    assert not result.success
    assert result.error_type == "database"
    assert "no_such_column" in result.error


def test_timeout_is_enforced():
    executor = QueryExecutor(validator=AllowEverything(), timeout_seconds=1)
    result = executor.execute("SELECT pg_sleep(5)")
    assert not result.success
    assert result.error_type == "timeout"
    assert result.execution_time_ms < 4000


def test_writes_fail_even_if_validation_is_bypassed():
    before = order_count()
    result = QueryExecutor(validator=AllowEverything()).execute(
        "DELETE FROM order_items RETURNING order_item_id"
    )
    assert not result.success
    assert result.error_type == "database"
    assert "read-only" in result.error
    assert order_count() == before


@pytest.mark.parametrize("table", ["messages", "conversations"])
def test_chat_history_is_unreadable_even_if_validation_is_bypassed(table):
    result = QueryExecutor(validator=AllowEverything()).execute(
        "SELECT * FROM {}".format(table)
    )
    assert not result.success
    assert result.error_type == "database"
    assert "permission denied" in result.error


def test_agent_role_cannot_write_even_in_a_read_write_transaction():
    before = order_count()
    for statement in ("DELETE FROM orders", "CREATE TABLE agent_scratch (id int)"):
        with agent_engine.connect() as conn:
            # Switch off the role's read-only default, leaving only its permissions.
            conn.execute(text("SET TRANSACTION READ WRITE"))
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text(statement))
    assert order_count() == before


def test_connection_is_usable_after_a_failed_query():
    query_executor.execute("SELECT no_such_column FROM orders")
    assert query_executor.execute("SELECT 1 AS one").rows == [[1]]

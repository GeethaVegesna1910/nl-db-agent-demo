"""Tests for the AI SQL generator.

These call the real Claude API (a few cents per run), so they need
ANTHROPIC_API_KEY in .env and the Phase 1 database to be running.

Run with pytest, or directly to see a PASS/FAIL line per check:
    python tests/test_sql_generator.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.config import settings
from app.database.connection import check_connection
from app.database.executor import query_executor
from app.llm.query_generator import (
    CANNOT_ANSWER, REFUSED, QueryGenerator, QuestionRejected, SQLGenerationError,
)
from app.security.sql_validator import sql_validator

READY = bool(settings.anthropic_api_key) and check_connection()
needs_claude = pytest.mark.skipif(
    not READY, reason="needs ANTHROPIC_API_KEY and the running database"
)


def run(sql):
    """Check the SQL is a valid SELECT and actually runs. Return the result."""
    assert sql_validator.validate(sql).is_valid, sql
    result = query_executor.execute(sql)
    assert result.success, "{}\n{}".format(result.error, sql)
    return result


@needs_claude
def test_total_revenue():
    result = run(QueryGenerator().generate_sql("total revenue"))
    assert result.row_count == 1
    assert float(result.rows[0][0]) > 0


@needs_claude
def test_top_5_products_by_quantity_sold():
    sql = QueryGenerator().generate_sql("top 5 products by quantity sold")
    result = run(sql)
    assert result.row_count == 5
    assert "order_items" in sql.lower()


@needs_claude
def test_delete_all_orders_is_refused():
    with pytest.raises(QuestionRejected) as caught:
        QueryGenerator().generate_sql("delete all orders")
    assert caught.value.kind == REFUSED
    assert caught.value.reason


@needs_claude
def test_weather_cannot_be_answered():
    with pytest.raises(QuestionRejected) as caught:
        QueryGenerator().generate_sql("what is the weather today")
    assert caught.value.kind == CANNOT_ANSWER
    assert caught.value.reason


@needs_claude
def test_follow_up_uses_the_conversation_context():
    # Same shape as the text ConversationStore.build_context() returns.
    context = (
        "User: revenue by country\n"
        "Assistant: Here is the revenue for each country.\n"
        "SQL used: SELECT c.country, SUM(o.total_amount) AS revenue FROM orders o "
        "JOIN customers c ON c.customer_id = o.customer_id "
        "WHERE o.status = 'completed' GROUP BY c.country ORDER BY revenue DESC"
    )
    sql = QueryGenerator().generate_sql("and by category instead?", context=context)
    result = run(sql)
    lowered = sql.lower()
    assert "group by" in lowered and "category" in lowered, sql
    assert "country" not in lowered, sql
    assert result.row_count > 1


# --- The retry loop, tested with a pretend Claude (no API call, always runs) ---

class Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class Response:
    stop_reason = "end_turn"

    def __init__(self, text):
        self.content = [Block(text)]


class FakeClaude:
    """Stands in for the Anthropic client and replays a fixed list of replies."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.requests = []
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        self.requests.append([dict(m) for m in kwargs["messages"]])
        return Response(self._replies.pop(0))


class FakeSchema:
    def describe(self):
        return "TABLE orders\n  order_id INTEGER"


def test_retry_tells_claude_what_was_wrong():
    claude = FakeClaude(["DELETE FROM orders", "```sql\nSELECT count(*) FROM orders;\n```"])
    sql = QueryGenerator(client=claude, schema=FakeSchema()).generate_sql("how many orders?")
    assert sql == "SELECT count(*) FROM orders"
    assert len(claude.requests) == 2
    assert "Only SELECT queries are allowed" in claude.requests[1][-1]["content"]


def test_gives_up_after_three_retries():
    claude = FakeClaude(["SELECT * FROM messages"] * 4)
    with pytest.raises(SQLGenerationError):
        QueryGenerator(client=claude, schema=FakeSchema()).generate_sql("show me the chats")
    assert len(claude.requests) == 4  # the first try + 3 retries


if __name__ == "__main__":
    # Plain runner: one PASS or FAIL line per test.
    if not READY:
        sys.exit("FAIL  needs ANTHROPIC_API_KEY in .env and the running database")
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_")]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS  {}".format(name))
        except Exception as exc:  # AssertionError included
            failures += 1
            print("FAIL  {}  ({}: {})".format(name, type(exc).__name__, exc))
    print("\n{} of {} passed".format(len(tests) - failures, len(tests)))
    sys.exit(1 if failures else 0)

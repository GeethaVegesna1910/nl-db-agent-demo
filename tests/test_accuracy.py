"""Accuracy checks: does the agent get the same numbers as SQL written by hand?

Each case has a question and the correct SQL for it, following the definitions
in metadata/business_semantics.yaml. The hand-written SQL is run first to get
the true numbers, then the agent is asked the same question in plain English
and its rows are compared with them.

These call the real Claude API (a few cents per run), so they need
ANTHROPIC_API_KEY in .env and the Phase 1 database to be running.

Run with pytest, or directly to see PASS/FAIL lines and a final score:
    python tests/test_accuracy.py
"""
import sys
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import text

from app.agent import NLDBAgent
from app.config import settings
from app.database.connection import check_connection, engine
from app.database.executor import query_executor
from app.database.semantic_layer import SemanticLayer

READY = bool(settings.anthropic_api_key) and check_connection()
needs_claude = pytest.mark.skipif(
    not READY, reason="needs ANTHROPIC_API_KEY and the running database"
)

USER = "test-" + uuid.uuid4().hex  # a made-up user, so real chats are untouched
TOLERANCE = 0.01                   # numbers may differ by a rounding cent, no more

# kind "number": the correct SQL returns one value.
# kind "groups": the correct SQL returns (label, value) rows; "ordered" means the
#                agent's rows must also come in the same order (a "top N" list).
CASES = [
    {
        "question": "What is the total revenue?",
        "kind": "number",
        "sql": "SELECT SUM(total_amount) FROM orders WHERE status = 'completed'",
    },
    {
        "question": "Show revenue by country",
        "kind": "groups",
        "sql": (
            "SELECT c.country, SUM(o.total_amount) FROM orders o "
            "JOIN customers c ON c.customer_id = o.customer_id "
            "WHERE o.status = 'completed' GROUP BY c.country"
        ),
    },
    {
        "question": "Show revenue by category",
        "kind": "groups",
        # Line items, not orders.total_amount: see the double-counting rule.
        "sql": (
            "SELECT p.category, SUM(oi.quantity * oi.unit_price) FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON p.product_id = oi.product_id "
            "WHERE o.status = 'completed' GROUP BY p.category"
        ),
    },
    {
        "question": "What are the top 5 products by quantity sold?",
        "kind": "groups",
        "ordered": True,
        "sql": (
            "SELECT p.name, SUM(oi.quantity) AS units FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON p.product_id = oi.product_id "
            "WHERE o.status = 'completed' GROUP BY p.name ORDER BY units DESC LIMIT 5"
        ),
    },
    {
        "question": "How many orders are there?",
        "kind": "number",
        "sql": "SELECT COUNT(*) FROM orders",
    },
    {
        "question": "How many customers do we have?",
        "kind": "number",
        "sql": "SELECT COUNT(*) FROM customers",
    },
    {
        "question": "What is the average order value?",
        "kind": "number",
        "sql": "SELECT AVG(total_amount) FROM orders WHERE status = 'completed'",
    },
    {
        "question": "How many orders were cancelled?",
        "kind": "number",
        "sql": "SELECT COUNT(*) FROM orders WHERE status = 'cancelled'",
    },
    {
        "question": "Which 5 products bring in the most revenue?",
        "kind": "groups",
        "ordered": True,
        "sql": (
            "SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON p.product_id = oi.product_id "
            "WHERE o.status = 'completed' GROUP BY p.name ORDER BY revenue DESC LIMIT 5"
        ),
    },
    {
        # A synonym from the definitions file: "turnover" means revenue.
        "question": "What was our turnover for each product category?",
        "kind": "groups",
        "sql": (
            "SELECT p.category, SUM(oi.quantity * oi.unit_price) FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON p.product_id = oi.product_id "
            "WHERE o.status = 'completed' GROUP BY p.category"
        ),
    },
]


def is_number(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def same_number(a, b):
    return is_number(a) and is_number(b) and abs(float(a) - float(b)) <= TOLERANCE


def check_case(case):
    """Raise AssertionError (with a readable reason) if the agent's numbers are wrong."""
    # 1. The truth, from the hand-written SQL.
    correct = query_executor.execute(case["sql"])
    assert correct.success, "hand-written SQL failed: {}".format(correct.error)

    # 2. The agent's attempt, from the plain-English question.
    result = NLDBAgent().ask(case["question"], user_id=USER)
    assert result["sql"], "agent wrote no SQL. It said: {}".format(result["answer"])
    rows = result["rows"]
    detail = "\n    agent SQL: {}\n    agent rows: {}".format(
        " ".join(result["sql"].split()), rows[:6]
    )

    # 3. Compare. Column names and extra columns don't matter, only the values.
    if case["kind"] == "number":
        expected = correct.rows[0][0]
        assert len(rows) == 1, "expected one row" + detail
        assert any(same_number(cell, expected) for cell in rows[0]), (
            "expected {}".format(expected) + detail
        )
        return

    assert len(rows) == len(correct.rows), (
        "expected {} rows, got {}".format(len(correct.rows), len(rows)) + detail
    )
    for position, (label, expected) in enumerate(correct.rows):
        if case.get("ordered"):
            candidates = [rows[position]]  # must be at the same rank
        else:
            candidates = rows
        matching = [row for row in candidates if label in row]
        assert matching, "no row for {!r}{}".format(
            label, " at position {}".format(position + 1) if case.get("ordered") else ""
        ) + detail
        assert any(same_number(cell, expected) for cell in matching[0]), (
            "{!r} should be {}".format(label, expected) + detail
        )


def delete_test_user():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM conversations WHERE user_id = :u"), {"u": USER})


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    if check_connection():
        delete_test_user()


@needs_claude
@pytest.mark.parametrize("case", CASES, ids=[c["question"] for c in CASES])
def test_agent_matches_hand_written_sql(case):
    check_case(case)


# --- The definitions file itself (no Claude or database needed) ---

def test_definitions_cover_the_key_metrics_and_the_double_counting_rule():
    layer = SemanticLayer()
    for name in ("revenue", "order_count", "customer_count", "average_order_value",
                 "top_products_by_quantity", "top_products_by_revenue"):
        assert layer.get_metric(name)["calculation"]
    assert {"sales", "turnover"} <= set(layer.get_metric("revenue")["synonyms"])
    assert layer.get_metric("revenue")["filter"] == "orders.status = 'completed'"

    prompt_text = layer.describe()
    assert "Also called: sales, turnover" in prompt_text
    assert "Never SUM (or AVG) orders.total_amount in a query that joins order_items" in prompt_text
    assert "order_items.quantity * order_items.unit_price" in prompt_text


def test_hand_written_sql_shows_why_the_rule_exists():
    """Joining order_items and summing the order total really does inflate revenue."""
    if not check_connection():
        pytest.skip("database is not running")
    right = query_executor.execute(CASES[0]["sql"]).rows[0][0]
    wrong = query_executor.execute(
        "SELECT SUM(o.total_amount) FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.order_id WHERE o.status = 'completed'"
    ).rows[0][0]
    by_items = query_executor.execute(
        "SELECT SUM(oi.quantity * oi.unit_price) FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 'completed'"
    ).rows[0][0]
    assert wrong > right * 2
    assert by_items == right


if __name__ == "__main__":
    # Plain runner: one PASS or FAIL line per question, then the score.
    if not READY:
        sys.exit("FAIL  needs ANTHROPIC_API_KEY in .env and the running database")
    passed = 0
    try:
        for case in CASES:
            try:
                check_case(case)
                passed += 1
                print("PASS  {}".format(case["question"]))
            except Exception as exc:  # AssertionError included
                print("FAIL  {}\n    {}: {}".format(case["question"], type(exc).__name__, exc))
    finally:
        delete_test_user()
    print("\nScore: {}/{}".format(passed, len(CASES)))
    sys.exit(0 if passed == len(CASES) else 1)

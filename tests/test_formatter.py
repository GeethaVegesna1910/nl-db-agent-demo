"""Tests for the result formatter. No API calls and no database: just rows in,
formatted result out.

Run with pytest, or directly to see a PASS/FAIL line per check:
    python tests/test_formatter.py
"""
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.format.result_formatter import EMPTY_SUMMARY, ResultFormatter, json_safe

formatter = ResultFormatter()


def test_single_number():
    out = formatter.format(
        "total revenue", "SELECT SUM(total_amount) AS total_revenue FROM orders",
        ["total_revenue"], [[Decimal("1234567.00")]],
    )
    assert out["chart"] == "number"
    assert out["summary"] == "Total revenue is $1,234,567."
    assert out["highlights"] == []


def test_counts_are_not_shown_as_money():
    out = formatter.format("how many orders are there", "SELECT COUNT(*) FROM orders", ["count"], [[2000]])
    assert out["chart"] == "number"
    assert out["summary"] == "The count is 2,000."


def test_category_plus_number_is_a_bar_and_names_the_top_item():
    out = formatter.format(
        "revenue by country", "SELECT country, SUM(...) AS revenue ... GROUP BY country",
        ["country", "revenue"],
        # Deliberately not sorted, to prove the top item is found by value.
        [["Canada", Decimal("300000")], ["United States", Decimal("345000")],
         ["Mexico", Decimal("287142.86")], ["Brazil", Decimal("300000")]],
    )
    assert out["chart"] == "bar"
    assert out["summary"] == (
        "United States is the top country by revenue with $345,000 (28% of the total)."
    )


def test_date_plus_number_is_a_line():
    out = formatter.format(
        "revenue by month", "SELECT date_trunc('month', order_date) AS month, ...",
        ["month", "revenue"],
        [[datetime(2026, 1, 1), Decimal("100.00")],
         [datetime(2026, 2, 1), Decimal("250.50")],
         [datetime(2026, 3, 1), Decimal("175.25")]],
    )
    assert out["chart"] == "line"
    assert out["summary"] == (
        "Across 3 periods from Jan 2026 to Mar 2026, revenue peaked at $250.50 (Feb 2026)."
    )


def test_empty_result():
    for rows in ([], [[None]]):  # no rows at all, or SUM() over nothing
        out = formatter.format("revenue in 1999", "SELECT ...", ["revenue"], rows)
        assert out["summary"] == EMPTY_SUMMARY == "No matching rows found."
        assert out["chart"] == "table"
        assert out["highlights"] == []
        assert len(out["follow_ups"]) >= 2


def test_highlight_when_one_item_is_more_than_half():
    out = formatter.format(
        "revenue by category", "SELECT ...", ["category", "revenue"],
        [["Electronics", 900], ["Furniture", 50], ["Home & Kitchen", 30], ["Sports", 20]],
    )
    assert out["highlights"] == [
        "Electronics makes up 90% of the total, more than everything else combined."
    ]


def test_highlight_for_an_outlier():
    out = formatter.format(
        "orders per day", "SELECT ...", ["order_day", "orders"],
        [[date(2026, 1, 1), 3], [date(2026, 1, 2), 4], [date(2026, 1, 3), 40],
         [date(2026, 1, 4), 2], [date(2026, 1, 5), 3]],
    )
    assert out["chart"] == "line"
    assert out["highlights"] == ["2026-01-03 (40) is 3.8 times the average of 10.4."]

    # Evenly spread values have nothing worth pointing out.
    calm = formatter.format(
        "revenue by category", "SELECT ...", ["category", "revenue"],
        [["A", 100], ["B", 110], ["C", 95], ["D", 105]],
    )
    assert calm["highlights"] == []


def test_none_values_are_handled():
    out = formatter.format(
        "revenue by country", "SELECT ...", ["country", "revenue"],
        [["USA", Decimal("100")], [None, Decimal("40")], ["Canada", None]],
    )
    assert out["chart"] == "bar"
    assert out["summary"].startswith("USA is the top country by revenue with $100")
    assert "1 row has no value for revenue." in out["highlights"]


def test_top_n_does_not_claim_a_share_of_the_total():
    out = formatter.format(
        "top 3 products by quantity sold", "SELECT ... ORDER BY 4 DESC LIMIT 3",
        ["product_id", "name", "category", "total_quantity_sold"],
        [[22, "Resistance Bands Set", "Sports & Outdoors", 458],
         [13, "Stainless Steel Water Bottle", "Home & Kitchen", 432],
         [4, "Wireless Mouse", "Electronics", 411]],
    )
    assert out["chart"] == "bar"
    assert out["summary"] == "Resistance Bands Set is the top result by total quantity sold with 458."


def test_anything_else_is_a_table():
    out = formatter.format(
        "list customers", "SELECT ...", ["first_name", "city", "signup_date"],
        [["Ana", "Austin", date(2025, 1, 2)], ["Bo", "Boston", date(2025, 3, 4)]],
    )
    assert out["chart"] == "table"
    assert out["summary"] == "Found 2 rows with first name, city and signup date."


def test_follow_ups_are_built_from_the_columns():
    out = formatter.format(
        "revenue by country", "SELECT ...", ["country", "revenue"],
        [[name, value] for name, value in
         [("A", 60), ("B", 50), ("C", 40), ("D", 30), ("E", 20), ("F", 10)]],
    )
    assert out["follow_ups"] == [
        "Show it by category instead", "What are the top 5?", "How has it changed by month?"
    ]
    # Already by category: suggest something else, never the same breakdown.
    by_category = formatter.format(
        "revenue by category", "SELECT ...", ["category", "revenue"], [["A", 60], ["B", 50]]
    )
    assert 2 <= len(by_category["follow_ups"]) <= 3
    assert not any("category" in idea for idea in by_category["follow_ups"])


def test_whole_output_can_be_turned_into_json():
    columns = ["day", "label", "amount", "created_at", "nothing"]
    rows = [
        [date(2026, 10, 9), "a", Decimal("12.50"), datetime(2026, 10, 9, 8, 30), None],
        [date(2026, 10, 10), None, Decimal("7"), datetime(2026, 10, 10, 9, 0), None],
    ]
    out = formatter.format("amount per day", "SELECT ...", columns, rows)
    # The formatter's own output, plus the rows once made JSON-friendly.
    text = json.dumps({"formatted": out, "columns": columns, "rows": json_safe(rows)})
    back = json.loads(text)
    assert back["rows"][0] == ["2026-10-09", "a", 12.5, "2026-10-09T08:30:00", None]
    assert back["rows"][1][2] == 7
    assert set(back["formatted"]) == {"summary", "chart", "highlights", "follow_ups"}


if __name__ == "__main__":
    # Plain runner: one PASS or FAIL line per test.
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

"""End-to-end tests for the agent.

Most of these call the real Claude API (a few cents per run), so they need
ANTHROPIC_API_KEY in .env and the Phase 1 database to be running.

Run with pytest, or directly to see a PASS/FAIL line per check:
    python tests/test_agent.py
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import text

from app.agent import GENERAL_ERROR, NLDBAgent
from app.config import settings
from app.context.conversation_store import ConversationStore
from app.database.connection import check_connection, engine

DB_READY = check_connection()
pytestmark = pytest.mark.skipif(not DB_READY, reason="database is not running")
needs_claude = pytest.mark.skipif(not settings.anthropic_api_key, reason="needs ANTHROPIC_API_KEY")

# A made-up user, so these tests never touch real conversations.
USER = "test-" + uuid.uuid4().hex
_first = {}


def first_turn():
    """Ask the opening question once; the tests below all build on that conversation."""
    if not _first:
        _first.update(NLDBAgent().ask("show revenue by country", user_id=USER))
    return _first


def delete_test_user():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM conversations WHERE user_id = :u"), {"u": USER})


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    delete_test_user()


def order_count():
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM orders")).scalar()


@needs_claude
def test_first_question_starts_a_conversation_and_returns_rows():
    result = first_turn()
    assert isinstance(result["conversation_id"], int)
    assert isinstance(result["answer"], str) and result["answer"]
    assert "country" in result["sql"].lower()
    assert result["columns"] and result["rows"]
    # The formatter's additions (Phase 7), and the whole answer is JSON-friendly.
    assert result["summary"] == result["answer"]
    assert result["chart"] in ("number", "bar", "line", "table")
    assert isinstance(result["highlights"], list)
    assert 2 <= len(result["follow_ups"]) <= 3
    json.dumps(result)

    history = ConversationStore().get_history(result["conversation_id"])
    assert [m["role"] for m in history[:2]] == ["user", "assistant"]
    assert history[0]["content"] == "show revenue by country"
    assert history[1]["content"] == result["summary"]
    assert history[1]["sql_used"] == result["sql"]


@needs_claude
def test_follow_up_in_same_conversation_groups_by_category():
    chat = first_turn()["conversation_id"]
    result = NLDBAgent().ask("and by category instead?", conversation_id=chat, user_id=USER)
    sql = result["sql"].lower()
    assert result["conversation_id"] == chat
    assert "group by" in sql and "category" in sql, result["sql"]
    assert "country" not in sql, result["sql"]
    assert len(result["rows"]) > 1


@needs_claude
def test_new_agent_continues_the_conversation_after_a_restart():
    chat = first_turn()["conversation_id"]
    before = len(ConversationStore().get_history(chat, limit=100))

    # A brand new agent has nothing in memory, just like after a restart.
    restarted = NLDBAgent()
    result = restarted.ask("which country is highest?", conversation_id=chat, user_id=USER)

    assert result["conversation_id"] == chat
    # Only the saved chat explains that "highest" means highest revenue.
    sql = (result["sql"] or "").lower()
    assert "country" in sql and ("total_amount" in sql or "unit_price" in sql), result["sql"]
    assert result["rows"]
    assert len(ConversationStore().get_history(chat, limit=100)) == before + 2


@needs_claude
def test_delete_is_refused_and_the_refusal_is_saved():
    chat = first_turn()["conversation_id"]
    orders_before = order_count()

    result = NLDBAgent().ask("delete all orders", conversation_id=chat, user_id=USER)

    assert result["sql"] is None
    assert result["columns"] == [] and result["rows"] == []
    assert result["answer"] and result["summary"] == result["answer"]
    assert result["chart"] is None
    assert result["highlights"] == [] and result["follow_ups"] == []
    assert order_count() == orders_before

    question, refusal = ConversationStore().get_history(chat, limit=2)
    assert (question["role"], question["content"]) == ("user", "delete all orders")
    assert (refusal["role"], refusal["content"]) == ("assistant", result["answer"])
    assert refusal["sql_used"] is None


# --- No Claude needed below: the generator is replaced by a pretend one ---

class BrokenGenerator:
    def generate_sql(self, question, context=None):
        raise RuntimeError("network is down: secret-internal-detail")


def test_unexpected_failure_gives_a_friendly_answer_and_is_saved():
    result = NLDBAgent(generator=BrokenGenerator()).ask("total revenue", user_id=USER)
    assert result["answer"] == GENERAL_ERROR
    assert result["sql"] is None and result["rows"] == []
    history = ConversationStore().get_history(result["conversation_id"])
    assert [m["content"] for m in history] == ["total revenue", GENERAL_ERROR]


def test_cannot_continue_a_conversation_that_is_not_yours():
    someone_elses = NLDBAgent(generator=BrokenGenerator()).ask("hello", user_id=USER)
    with pytest.raises(ValueError):
        NLDBAgent(generator=BrokenGenerator()).ask(
            "hello", conversation_id=someone_elses["conversation_id"], user_id=USER + "-other"
        )


if __name__ == "__main__":
    # Plain runner: one PASS or FAIL line per test.
    if not (DB_READY and settings.anthropic_api_key):
        sys.exit("FAIL  needs ANTHROPIC_API_KEY in .env and the running database")
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_")]
    failures = 0
    try:
        for name, fn in tests:
            try:
                fn()
                print("PASS  {}".format(name))
            except Exception as exc:  # AssertionError included
                failures += 1
                print("FAIL  {}  ({}: {})".format(name, type(exc).__name__, exc))
    finally:
        delete_test_user()
    print("\n{} of {} passed".format(len(tests) - failures, len(tests)))
    sys.exit(1 if failures else 0)

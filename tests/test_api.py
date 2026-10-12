"""Tests for the web API, using FastAPI's TestClient (no server needs to be running).

The AI is replaced by a pretend SQL generator, so these cost nothing. Everything
else is real: the agent, the read-only executor, the formatter and the chat
history tables. They need the Phase 1 database to be running.

Run with pytest, or directly to see a PASS/FAIL line per check:
    python tests/test_api.py
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import text

from app.agent import NLDBAgent
from app.api.main import ALLOWED_ORIGINS, SERVER_ERROR, app, get_agent
from app.database.connection import check_connection, engine
from app.llm.query_generator import REFUSED, QuestionRejected

DB_READY = check_connection()
pytestmark = pytest.mark.skipif(not DB_READY, reason="database is not running")

# Made-up users, so these tests never touch real conversations.
USER = "test-" + uuid.uuid4().hex
OTHER_USER = "test-" + uuid.uuid4().hex

REFUSAL = "I can only read data, so I can't delete orders."


class PretendGenerator:
    """Stands in for Claude: fixed SQL for normal questions, a refusal for 'delete'."""

    def generate_sql(self, question, context=None):
        if "delete" in question.lower():
            raise QuestionRejected(REFUSED, REFUSAL)
        if "explode" in question.lower():
            raise RuntimeError("secret internal detail")
        return (
            "SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue "
            "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON p.product_id = oi.product_id "
            "WHERE o.status = 'completed' GROUP BY p.category ORDER BY revenue DESC"
        )


class BrokenAgent:
    def ask(self, *args, **kwargs):
        raise RuntimeError("secret internal detail")


# The real agent with the pretend generator plugged in.
app.dependency_overrides[get_agent] = lambda: NLDBAgent(generator=PretendGenerator())
# "with" makes the app run its startup code, as a real server would.
_client = None


def client():
    global _client
    if _client is None:
        _client = TestClient(app)
        _client.__enter__()
    return _client


def ask(question, **extra):
    body = {"question": question, "user_id": USER}
    body.update(extra)
    return client().post("/query", json=body)


def delete_test_users():
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM conversations WHERE user_id IN (:a, :b)"),
            {"a": USER, "b": OTHER_USER},
        )


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    if DB_READY:
        delete_test_users()


def test_health():
    response = client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database_connected": True}
    assert len(response.headers["X-Request-ID"]) == 8


def test_normal_question_returns_the_expected_fields():
    response = ask("show revenue by category")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "conversation_id", "summary", "sql", "columns", "rows",
        "chart", "highlights", "follow_ups",
    }
    assert isinstance(data["conversation_id"], int)
    assert data["columns"] == ["category", "revenue"]
    assert len(data["rows"]) == 4 and isinstance(data["rows"][0][1], float)
    assert data["chart"] == "bar"
    assert data["summary"].endswith("of the total).")
    assert data["sql"].startswith("SELECT")
    assert len(data["follow_ups"]) >= 2


def test_empty_question_is_rejected():
    for question in ("", "   "):
        response = ask(question)
        assert response.status_code == 422
        assert response.json() == {"detail": "The question must not be empty."}
    # Leaving the question out altogether is also explained clearly.
    missing = client().post("/query", json={"user_id": USER})
    assert missing.status_code == 422
    assert missing.json() == {"detail": "question: Field required"}


def test_too_long_question_is_rejected():
    response = ask("x" * 501)
    assert response.status_code == 422
    assert "too long (501 characters)" in response.json()["detail"]
    assert ask("x" * 500).status_code == 200  # exactly at the limit is fine


def test_refused_question_gets_a_polite_answer_and_no_sql():
    response = ask("delete all orders")
    assert response.status_code == 200  # a refusal is an answer, not an error
    data = response.json()
    assert data["summary"] == REFUSAL
    assert data["sql"] is None
    assert data["columns"] == [] and data["rows"] == []
    assert data["chart"] is None


def test_continuing_a_conversation_keeps_the_same_id():
    first = ask("show revenue by category").json()
    second = ask("and again", conversation_id=first["conversation_id"]).json()
    assert second["conversation_id"] == first["conversation_id"]

    listed = client().get("/conversations", params={"user_id": USER}).json()["conversations"]
    assert listed[0]["id"] == first["conversation_id"]  # most recently used comes first
    assert listed[0]["title"] == "show revenue by category"


def test_someone_elses_conversation_gives_404():
    mine = ask("show revenue by category").json()["conversation_id"]
    not_found = {"detail": "Conversation not found."}

    # Another user cannot read it...
    read = client().get("/conversations/{}/messages".format(mine), params={"user_id": OTHER_USER})
    assert (read.status_code, read.json()) == (404, not_found)
    # ...or add to it...
    write = client().post(
        "/query", json={"question": "hello", "conversation_id": mine, "user_id": OTHER_USER}
    )
    assert (write.status_code, write.json()) == (404, not_found)
    # ...and it is not in their list.
    assert client().get("/conversations", params={"user_id": OTHER_USER}).json() == {"conversations": []}
    # A conversation that does not exist looks exactly the same.
    missing = client().get("/conversations/999999999/messages", params={"user_id": USER})
    assert (missing.status_code, missing.json()) == (404, not_found)


def test_messages_endpoint_returns_history_in_order():
    first = ask("show revenue by category").json()
    chat = first["conversation_id"]
    ask("delete all orders", conversation_id=chat)

    response = client().get("/conversations/{}/messages".format(chat), params={"user_id": USER})
    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == chat
    assert [(m["role"], m["content"]) for m in data["messages"]] == [
        ("user", "show revenue by category"),
        ("assistant", first["summary"]),
        ("user", "delete all orders"),
        ("assistant", REFUSAL),
    ]
    assert data["messages"][1]["sql_used"] == first["sql"]
    assert data["messages"][3]["sql_used"] is None


def test_errors_never_show_a_python_trace():
    # A failure inside the agent's pipeline becomes a friendly answer...
    handled = ask("please explode")
    assert handled.status_code == 200
    assert "secret" not in handled.text and "Traceback" not in handled.text

    # ...and even a crash nobody planned for becomes a friendly 500.
    real_agent = app.dependency_overrides[get_agent]
    app.dependency_overrides[get_agent] = lambda: BrokenAgent()
    try:
        crashed = ask("anything")
    finally:
        app.dependency_overrides[get_agent] = real_agent
    assert crashed.status_code == 500
    body = crashed.json()
    assert body["detail"] == SERVER_ERROR
    assert body["request_id"] == crashed.headers["X-Request-ID"]
    assert "secret" not in crashed.text and "Traceback" not in crashed.text


def metric(name, **labels):
    """Current value of one counter (0 if it has never been touched)."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_metrics_endpoint_lists_the_counters():
    response = client().get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    for name in (
        "nldb_http_requests_total",
        "nldb_http_request_duration_seconds_bucket",
        "nldb_questions_answered_total",
        'nldb_questions_rejected_total{reason="refused"}',
        'nldb_questions_rejected_total{reason="cannot_answer"}',
        'nldb_errors_total{kind="question"}',
        'nldb_errors_total{kind="server"}',
    ):
        assert name in response.text, name


def test_metrics_count_requests_by_endpoint_and_status():
    ok = dict(method="GET", endpoint="/health", status="200")
    before = metric("nldb_http_requests_total", **ok)
    timed_before = metric("nldb_http_request_duration_seconds_count", method="GET", endpoint="/health")
    client().get("/health")
    client().get("/health")
    assert metric("nldb_http_requests_total", **ok) == before + 2
    assert metric("nldb_http_request_duration_seconds_count", method="GET", endpoint="/health") == timed_before + 2

    # Failures are counted under their own status...
    rejected = dict(method="POST", endpoint="/query", status="422")
    before = metric("nldb_http_requests_total", **rejected)
    ask("")
    assert metric("nldb_http_requests_total", **rejected) == before + 1

    # ...and chat ids are folded into one endpoint name, however many chats exist.
    pattern = dict(method="GET", endpoint="/conversations/{conversation_id}/messages", status="404")
    before = metric("nldb_http_requests_total", **pattern)
    client().get("/conversations/999999998/messages", params={"user_id": USER})
    client().get("/conversations/999999999/messages", params={"user_id": USER})
    assert metric("nldb_http_requests_total", **pattern) == before + 2
    assert "999999999" not in client().get("/metrics").text

    # Addresses that don't exist share one name too.
    unmatched = dict(method="GET", endpoint="unmatched", status="404")
    before = metric("nldb_http_requests_total", **unmatched)
    client().get("/no-such-page")
    assert metric("nldb_http_requests_total", **unmatched) == before + 1


def test_metrics_count_answered_refused_and_failed_questions():
    answered = metric("nldb_questions_answered_total")
    refused = metric("nldb_questions_rejected_total", reason="refused")
    question_errors = metric("nldb_errors_total", kind="question")
    server_errors = metric("nldb_errors_total", kind="server")

    ask("show revenue by category")
    ask("delete all orders")
    ask("please explode")  # the pretend generator raises: a failed question

    assert metric("nldb_questions_answered_total") == answered + 1
    assert metric("nldb_questions_rejected_total", reason="refused") == refused + 1
    assert metric("nldb_errors_total", kind="question") == question_errors + 1
    assert metric("nldb_errors_total", kind="server") == server_errors

    # A crash nobody planned for is counted as a server error.
    real_agent = app.dependency_overrides[get_agent]
    app.dependency_overrides[get_agent] = lambda: BrokenAgent()
    try:
        ask("anything")
    finally:
        app.dependency_overrides[get_agent] = real_agent
    assert metric("nldb_errors_total", kind="server") == server_errors + 1


def test_cors_allows_the_website_and_nobody_else():
    for origin in ALLOWED_ORIGINS:
        response = client().get("/health", headers={"Origin": origin})
        assert response.headers["access-control-allow-origin"] == origin
    stranger = client().get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in stranger.headers


if __name__ == "__main__":
    # Plain runner: one PASS or FAIL line per test.
    if not DB_READY:
        sys.exit("FAIL  the database is not running")
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
        delete_test_users()
    print("\n{} of {} passed".format(len(tests) - failures, len(tests)))
    sys.exit(1 if failures else 0)

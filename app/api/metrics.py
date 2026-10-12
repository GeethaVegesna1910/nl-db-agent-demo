"""Numbers about the running API, for Prometheus to collect.

Prometheus is a monitoring tool. Every few seconds it fetches GET /metrics,
which lists the counters below as plain text, and stores them so you can graph
how busy the service is and how often things go wrong.

Two kinds of metric are used:
    Counter    a number that only goes up (requests served, errors seen)
    Histogram  how long things took, grouped into time buckets
"""
from prometheus_client import Counter, Histogram

# Every HTTP request, labelled so they can be split by endpoint and result.
# "endpoint" is the route pattern (/conversations/{conversation_id}/messages),
# not the real address, so thousands of chat ids don't become thousands of series.
REQUESTS = Counter(
    "nldb_http_requests_total",
    "HTTP requests handled, by method, endpoint and status code.",
    ["method", "endpoint", "status"],
)

REQUEST_SECONDS = Histogram(
    "nldb_http_request_duration_seconds",
    "Time taken to handle a request, in seconds.",
    ["method", "endpoint"],
    # A question waits on the AI, so it can take several seconds.
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60),
)

QUESTIONS_ANSWERED = Counter(
    "nldb_questions_answered_total",
    "Questions that were answered with data.",
)

# reason is "refused" (asked to change data) or "cannot_answer" (not in the database).
QUESTIONS_REJECTED = Counter(
    "nldb_questions_rejected_total",
    "Questions the agent declined, by reason.",
    ["reason"],
)

# kind is "question" (the agent could not produce an answer: AI or query failure)
# or "server" (an unexpected crash while handling any request).
ERRORS = Counter(
    "nldb_errors_total",
    "Things that went wrong, by kind.",
    ["kind"],
)

# Make every series show up in /metrics from the start with the value 0, so a
# dashboard can tell "nothing has gone wrong" apart from "not being measured".
for _reason in ("refused", "cannot_answer"):
    QUESTIONS_REJECTED.labels(reason=_reason)
for _kind in ("question", "server"):
    ERRORS.labels(kind=_kind)


def record_question(status: str) -> None:
    """Count one finished question. status comes from NLDBAgent.ask()."""
    if status == "answered":
        QUESTIONS_ANSWERED.inc()
    elif status in ("refused", "cannot_answer"):
        QUESTIONS_REJECTED.labels(reason=status).inc()
    else:
        ERRORS.labels(kind="question").inc()

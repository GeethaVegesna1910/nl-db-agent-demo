"""The web API: lets a website (or any program) talk to the agent over HTTP.

    GET  /health                           is the server up, and can it reach the database?
    POST /query                            ask a question
    GET  /conversations                    list a user's chats, newest first
    GET  /conversations/{id}/messages      read one chat's history
    GET  /metrics                          counters for Prometheus (monitoring)

Start it from the project folder with:
    uvicorn app.api.main:app --reload --port 8001
Then open http://localhost:8001/docs for a page where you can try each endpoint.

ABOUT user_id: it is a PLACEHOLDER until real sign-in exists. Right now the
caller simply tells us who they are and we believe them, so anyone could read
another user's chats by sending that user's id. Before real users arrive,
replace it with an identity taken from a verified login (a session or token),
never from the request itself.
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator

from app.agent import NLDBAgent
from app.api import metrics
from app.context.conversation_store import ConversationStore
from app.database.connection import check_connection

MAX_QUESTION_LENGTH = 500
MAX_USER_ID_LENGTH = 100
# Websites allowed to call this API from a browser (the future front end).
# 5173 is the Vite dev server, 8080 the Docker build of the site.
ALLOWED_ORIGINS = ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]
SERVER_ERROR = "Sorry, something went wrong on our side. Please try again."

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nl_db_agent.api")


# ----------------------------------------------------------------------
# Startup: build the shared objects once, not once per request
# ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Everything before "yield" runs when the server starts.
    app.state.store = ConversationStore()
    app.state.agent = NLDBAgent(store=app.state.store)
    logger.info("Agent ready")
    yield
    # Anything after "yield" would run when the server stops.


app = FastAPI(
    title="Natural-language database agent",
    description="Ask questions about the shop's data in plain English.",
    lifespan=lifespan,
)

# CORS: browsers block a web page from calling a different address unless that
# server says the page's address is allowed. These are the allowed ones.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID"],
)


def get_agent(request: Request) -> NLDBAgent:
    """Hand an endpoint the shared agent. (Tests swap in a pretend one here.)"""
    return request.app.state.agent


def get_store(request: Request) -> ConversationStore:
    return request.app.state.store


# ----------------------------------------------------------------------
# Every request: give it a short id, log it, and never leak a stack trace
# ----------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # A short id that appears in the log AND in the response, so a user who
    # reports a problem can quote it and we can find the matching log lines.
    request_id = uuid.uuid4().hex[:8]
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Something we did not plan for. The full details go to the log only;
        # the caller gets a friendly sentence, never a Python error trace.
        logger.exception("[%s] %s %s failed", request_id, request.method, request.url.path)
        metrics.ERRORS.labels(kind="server").inc()
        response = JSONResponse(
            status_code=500, content={"detail": SERVER_ERROR, "request_id": request_id}
        )
    elapsed_ms = (time.perf_counter() - started) * 1000

    # Count the request for monitoring. The route pattern is used as the name
    # ("/conversations/{conversation_id}/messages"), and anything that matched
    # no route is grouped together, so random addresses can't flood the metrics.
    route = request.scope.get("route")
    endpoint = getattr(route, "path", "unmatched")
    metrics.REQUESTS.labels(request.method, endpoint, str(response.status_code)).inc()
    metrics.REQUEST_SECONDS.labels(request.method, endpoint).observe(elapsed_ms / 1000)

    # The question text is deliberately not logged: it may contain private details.
    logger.info(
        "[%s] %s %s -> %s (%.0f ms)",
        request_id, request.method, request.url.path, response.status_code, elapsed_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def explain_bad_input(request: Request, exc: RequestValidationError):
    """Turn FastAPI's detailed validation errors into one readable sentence (HTTP 422)."""
    problems = []
    for error in exc.errors():
        field = str(error["loc"][-1]) if error.get("loc") else "request"
        message = error.get("msg", "is not valid")
        if message.startswith("Value error, "):
            # A message written by one of our own validators below: already a full sentence.
            problems.append(message[len("Value error, "):])
        else:
            problems.append("{}: {}".format(field, message))
    return JSONResponse(status_code=422, content={"detail": "; ".join(problems)})


# ----------------------------------------------------------------------
# What a request and a response look like
# ----------------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str
    conversation_id: Optional[int] = None  # leave out to start a new chat
    # Placeholder until real sign-in exists (see the note at the top of this file).
    user_id: str = Field(default="demo", min_length=1, max_length=MAX_USER_ID_LENGTH)

    @field_validator("question")
    @classmethod
    def question_must_be_usable(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("The question must not be empty.")
        if len(value) > MAX_QUESTION_LENGTH:
            raise ValueError(
                "The question is too long ({} characters). Please keep it under {}.".format(
                    len(value), MAX_QUESTION_LENGTH
                )
            )
        return value


class QueryResponse(BaseModel):
    conversation_id: int
    summary: str
    sql: Optional[str]       # None when the question was refused or failed
    columns: List[str]
    rows: List[List[Any]]
    chart: Optional[str]     # "number", "bar", "line", "table", or None
    highlights: List[str]
    follow_ups: List[str]


# Reused by the endpoints that take user_id in the address, e.g. ?user_id=demo
UserId = Query(
    default="demo", min_length=1, max_length=MAX_USER_ID_LENGTH,
    description="Placeholder until real sign-in exists.",
)


def require_conversation(store: ConversationStore, conversation_id: int, user_id: str) -> Dict[str, Any]:
    """Return the conversation, or answer 404.

    "Doesn't exist" and "belongs to someone else" get the same reply on purpose,
    so nobody can discover which conversation ids are in use.
    """
    conversation = store.get_conversation(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


# ----------------------------------------------------------------------
# Endpoints
# These are plain "def" (not "async def") on purpose: the agent waits on the
# AI and the database, and FastAPI runs plain functions in a worker thread so
# one slow question does not freeze the server for everyone else.
# ----------------------------------------------------------------------
@app.get("/health")
def health() -> Dict[str, Any]:
    """Is the server running, and can it reach the database?"""
    return {"status": "ok", "database_connected": check_connection()}


@app.post("/query", response_model=QueryResponse)
def query(
    body: QueryRequest,
    agent: NLDBAgent = Depends(get_agent),
    store: ConversationStore = Depends(get_store),
) -> Dict[str, Any]:
    """Ask a question. Send the returned conversation_id back to ask a follow-up."""
    if body.conversation_id is not None:
        require_conversation(store, body.conversation_id, body.user_id)
    # A refused question is not an error: the agent returns a polite sentence
    # as the summary, with sql set to None.
    result = agent.ask(body.question, conversation_id=body.conversation_id, user_id=body.user_id)
    metrics.record_question(result.get("status", "error"))
    return result


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Counters in the text format Prometheus reads. Not meant for people."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/conversations")
def list_conversations(
    user_id: str = UserId,
    store: ConversationStore = Depends(get_store),
) -> Dict[str, Any]:
    """This user's chats, most recently used first."""
    return {"conversations": store.list_conversations(user_id)}


@app.get("/conversations/{conversation_id}/messages")
def conversation_messages(
    conversation_id: int,
    user_id: str = UserId,
    limit: int = Query(default=50, ge=1, le=200, description="How many of the latest messages to return."),
    store: ConversationStore = Depends(get_store),
) -> Dict[str, Any]:
    """One chat's messages, oldest first."""
    conversation = require_conversation(store, conversation_id, user_id)
    return {
        "conversation_id": conversation_id,
        "title": conversation["title"],
        "messages": store.get_history(conversation_id, limit=limit),
    }

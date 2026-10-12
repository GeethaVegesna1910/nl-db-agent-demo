"""Turn a plain-English question into one safe SQL query, using Claude.

The flow for every question:

    1. Build a system prompt that describes the business tables and the
       business definitions (what "revenue" means, and so on).
    2. Send the question (plus recent chat, if any) to Claude.
    3. Claude replies with ONE of:
         - a SELECT statement
         - "REFUSED: <reason>"        the question asks to change data
         - "CANNOT_ANSWER: <reason>"  the tables don't hold that information
    4. A SELECT is checked by SQLValidator. If it fails, we tell Claude what was
       wrong and ask again, a few times at most.

This file only WRITES the SQL. Running it is the job of QueryExecutor (Phase 2),
which has its own safety checks. Claude's output is never trusted on its own.
"""
import re
from typing import Optional

import anthropic

from app.config import settings
from app.database.schema import SchemaIntrospector, schema_introspector
from app.database.semantic_layer import SemanticLayer, semantic_layer
from app.security.sql_validator import SQLValidator, sql_validator

# The two special replies Claude may give instead of SQL.
REFUSED = "REFUSED"
CANNOT_ANSWER = "CANNOT_ANSWER"

SYSTEM_PROMPT = """\
You write SQL for a natural-language database assistant. People ask questions \
about an online shop's data in plain English; your reply is passed straight to \
a program, not shown to a person, so it must be in exactly one of the three \
forms below with nothing before or after it.

The database is PostgreSQL 15. These are the only tables you can use:

<schema>
{schema}
</schema>

The business has agreed definitions for its key numbers. Follow them exactly, \
so the same question always gets the same answer. They take priority over your \
own reading of a word such as "revenue" or "top":

<business_definitions>
{semantics}
</business_definitions>

Reply forms:

1. If the question can be answered from these tables, reply with a single \
PostgreSQL SELECT statement (it may start with WITH). Output only the SQL: no \
explanation, no markdown code fences, no comments.

2. If the question asks to add, change or delete anything (data, tables, \
permissions, settings), reply with one line:
REFUSED: <short reason written for the person who asked>
This assistant is read-only, so such requests are never turned into SQL, even \
if the person says they are allowed.

3. If the question cannot be answered from these tables (for example it is \
about something the shop's data does not cover), reply with one line:
CANNOT_ANSWER: <short reason written for the person who asked>

Writing the SQL:
- Use only the tables and columns listed in the schema. Do not query system \
catalogs (pg_* or information_schema); a safety checker rejects them.
- Give calculated columns clear names with AS, so the result is readable.
- The user's message may include the recent conversation. Use it to work out \
what a short follow-up such as "and by category?" refers to: usually the same \
measure and filters as the previous question, with the one change asked for.
"""


class QuestionRejected(Exception):
    """Claude declined to write SQL for this question.

    kind is "REFUSED" (the question asks to change data) or "CANNOT_ANSWER"
    (the database doesn't hold the answer). reason is safe to show to the user.
    """

    def __init__(self, kind: str, reason: str):
        super().__init__("{}: {}".format(kind, reason))
        self.kind = kind
        self.reason = reason


class SQLGenerationError(Exception):
    """Claude could not produce SQL that passes the validator, even after retries."""


class QueryGenerator:
    def __init__(
        self,
        client: Optional[anthropic.Anthropic] = None,
        schema: Optional[SchemaIntrospector] = None,
        validator: Optional[SQLValidator] = None,
        semantics: Optional[SemanticLayer] = None,
        model: Optional[str] = None,
        max_retries: Optional[int] = None,
    ):
        # The key comes from .env (ANTHROPIC_API_KEY). It is never written in code.
        self._client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key or None
        )
        self._schema = schema or schema_introspector
        self._validator = validator or sql_validator
        self._semantics = semantics or semantic_layer
        self.model = model or settings.anthropic_model
        self.max_retries = settings.max_retries if max_retries is None else max_retries

    def generate_sql(self, question: str, context: Optional[str] = None) -> str:
        """Return one validated, read-only SELECT that answers the question.

        context is the text from ConversationStore.build_context(), so that a
        follow-up question can be understood.

        Raises QuestionRejected if Claude declines, and SQLGenerationError if no
        valid SQL comes back after the retries.
        """
        if not question or not question.strip():
            raise ValueError("question is empty")

        # The schema helper already hides the chat tables, so Claude never
        # learns they exist.
        system = SYSTEM_PROMPT.format(
            schema=self._schema.describe(),
            semantics=self._semantics.describe(),
        )
        messages = [{"role": "user", "content": self._user_message(question, context)}]

        error = None
        # One first try, plus up to max_retries corrections.
        for _ in range(1 + self.max_retries):
            response = self._ask(system, messages)
            reply = self._reply_text(response)

            # Claude said no: stop here and pass the reason on.
            for kind in (REFUSED, CANNOT_ANSWER):
                if reply.upper().startswith(kind + ":"):
                    raise QuestionRejected(kind, reply[len(kind) + 1:].strip())

            validation = self._validator.validate(reply)
            if validation.is_valid:
                return validation.sql

            # Not valid: show Claude its own answer and the reason, then loop.
            error = validation.error
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": (
                "A safety checker rejected that reply: {}\n"
                "Reply again in one of the three allowed forms."
            ).format(error)})

        raise SQLGenerationError(
            "No valid SQL after {} attempts. Last problem: {}".format(1 + self.max_retries, error)
        )

    def _ask(self, system: str, messages: list):
        """Send one request to Claude and return its response."""
        return self._client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=messages,
            # How hard Claude thinks before answering. Writing one query is a
            # small job, so "medium" is plenty.
            output_config={"effort": "medium"},
            # If the model's safety filter declines a request, let the API
            # retry it on a fallback model instead of failing outright.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    @staticmethod
    def _user_message(question: str, context: Optional[str]) -> str:
        if not context:
            return question
        return (
            "<conversation_so_far>\n{}\n</conversation_so_far>\n\n"
            "New question: {}"
        ).format(context, question)

    @staticmethod
    def _reply_text(response) -> str:
        """Pull the plain text out of Claude's response."""
        if response.stop_reason == "refusal":
            # The model's own safety filter stopped the request.
            raise QuestionRejected(REFUSED, "The AI model declined this request.")
        # A response is a list of blocks; only the "text" ones hold the answer.
        reply = "".join(b.text for b in response.content if b.type == "text").strip()
        # Remove a ```sql ... ``` wrapper, in case Claude adds one anyway.
        fenced = re.fullmatch(r"```[a-zA-Z]*\s*(.*?)\s*```", reply, re.DOTALL)
        return fenced.group(1).strip() if fenced else reply

"""The agent: one place that connects every earlier phase.

    question
       -> ConversationStore   recent chat, so follow-ups make sense   (Phase 3)
       -> QueryGenerator      Claude writes one SELECT                (Phase 4)
       -> QueryExecutor       runs it as the read-only database user  (Phase 2)
       -> ConversationStore   saves the question and the answer       (Phase 3)

The agent keeps nothing in memory between questions. Everything it needs to
continue a chat is in the database, so a new NLDBAgent (after a restart, or ten
days later) carries on from the conversation_id alone.
"""
from typing import Any, Dict, List, Optional

from app.context.conversation_store import ConversationStore
from app.database.executor import QueryExecutor, QueryResult
from app.llm.query_generator import QueryGenerator, QuestionRejected

# Shown instead of technical details when something breaks.
GENERAL_ERROR = "Sorry, something went wrong while answering that. Please try again."
QUERY_ERROR = "Sorry, I couldn't run a query for that question. Try asking it another way."
TIMEOUT_ERROR = "Sorry, that question took too long to answer. Try a narrower one."

TITLE_LENGTH = 60  # a conversation's title is the start of its first question


class NLDBAgent:
    def __init__(
        self,
        store: Optional[ConversationStore] = None,
        generator: Optional[QueryGenerator] = None,
        executor: Optional[QueryExecutor] = None,
    ):
        self._store = store or ConversationStore()
        self._executor = executor or QueryExecutor()
        # Created on first use, so listing or reading chats works without an API key.
        self._generator = generator

    def ask(
        self,
        question: str,
        conversation_id: Optional[int] = None,
        user_id: str = "demo",
    ) -> Dict[str, Any]:
        """Answer one question and remember the exchange.

        Returns a dict with: conversation_id, answer, sql, columns, rows.
        Pass the returned conversation_id back in to ask a follow-up.
        """
        question = (question or "").strip()
        if not question:
            raise ValueError("question is empty")

        # 1. Find the conversation, or start a new one named after the question.
        if conversation_id is None:
            conversation_id = self._store.create_conversation(
                user_id, title=question[:TITLE_LENGTH]
            )
        elif conversation_id not in [c["id"] for c in self._store.list_conversations(user_id)]:
            # Also stops one user from continuing another user's chat.
            raise ValueError("No conversation {} for user {!r}".format(conversation_id, user_id))

        # 2. Read the recent turns BEFORE saving the new question, so the
        #    question does not appear twice in what Claude sees.
        context = self._store.build_context(conversation_id)

        sql: Optional[str] = None
        saved_sql: Optional[str] = None
        columns: List[str] = []
        rows: List[List[Any]] = []
        try:
            # 3. Claude writes the SQL (already checked by the validator).
            if self._generator is None:
                self._generator = QueryGenerator()
            sql = self._generator.generate_sql(question, context or None)

            # 4. Run it as the read-only database user.
            result = self._executor.execute(sql)
            if result.success:
                answer = self._describe(result)
                columns, rows = result.columns, result.rows
                saved_sql = sql
            else:
                answer = TIMEOUT_ERROR if result.error_type == "timeout" else QUERY_ERROR
        except QuestionRejected as rejected:
            # Claude declined (data change, or not in the database). Its reason
            # is written for the user, so it becomes the answer. No SQL exists.
            answer = rejected.reason
        except Exception:
            # Anything else (network down, bad API key, ...). The user gets a
            # friendly sentence rather than a stack trace.
            answer = GENERAL_ERROR

        # 5. Remember both sides. Only SQL that actually worked is saved, so a
        #    broken query is never offered to Claude as an example later.
        self._store.add_message(conversation_id, "user", question)
        self._store.add_message(conversation_id, "assistant", answer, sql_used=saved_sql)

        return {
            "conversation_id": conversation_id,
            "answer": answer,
            "sql": sql,
            "columns": columns,
            "rows": rows,
        }

    @staticmethod
    def _describe(result: QueryResult) -> str:
        """Sum up a query result in one short sentence."""
        if result.row_count == 0:
            return "No matching data was found."
        if result.row_count == 1 and len(result.columns) == 1:
            # A single number or name, e.g. "total_revenue: 48210.50"
            return "{}: {}".format(result.columns[0].replace("_", " "), result.rows[0][0])
        sentence = "Found {} row{} showing {}.".format(
            result.row_count,
            "" if result.row_count == 1 else "s",
            ", ".join(c.replace("_", " ") for c in result.columns),
        )
        if result.truncated:
            sentence += " There are more rows than this; only the first ones are shown."
        return sentence

"""Conversation memory: save chat messages in PostgreSQL so they survive restarts.

Nothing is kept in Python memory. Every method reads from or writes to the
database, so a brand new ConversationStore (for example after the app restarts)
sees exactly the same conversations as the old one.

Every query below uses parameters (the ':name' placeholders). The values are
sent to the database separately from the SQL text, so text typed by a user can
never be run as SQL.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database.connection import engine as default_engine

# The only two speakers in a chat. The database enforces this too (CHECK constraint).
VALID_ROLES = ("user", "assistant")


class ConversationStore:
    def __init__(self, engine: Optional[Engine] = None):
        # Reuse the shared connection pool from Phase 2 unless a test passes its own.
        self._engine = engine or default_engine

    def create_conversation(self, user_id: str = "demo", title: Optional[str] = None) -> int:
        """Start a new conversation and return its id. Keep the id to add messages later."""
        # engine.begin() opens a transaction and commits it when the block ends.
        with self._engine.begin() as conn:
            return conn.execute(
                text(
                    "INSERT INTO conversations (user_id, title) "
                    "VALUES (:user_id, :title) RETURNING id"
                ),
                {"user_id": user_id, "title": title},
            ).scalar_one()

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        sql_used: Optional[str] = None,
    ) -> int:
        """Save one message and return its id.

        role is 'user' (the question) or 'assistant' (the answer).
        sql_used is the SQL the assistant ran to get its answer, if any.
        """
        if role not in VALID_ROLES:
            raise ValueError("role must be 'user' or 'assistant', got {!r}".format(role))

        # Both statements run in one transaction: either both happen or neither does.
        with self._engine.begin() as conn:
            # Mark the conversation as just used, so it moves to the top of
            # list_conversations(). This also tells us whether the conversation exists.
            updated = conn.execute(
                text("UPDATE conversations SET last_active_at = now() WHERE id = :id"),
                {"id": conversation_id},
            )
            if updated.rowcount == 0:
                raise ValueError("Unknown conversation: {}".format(conversation_id))

            return conn.execute(
                text(
                    "INSERT INTO messages (conversation_id, role, content, sql_used) "
                    "VALUES (:conversation_id, :role, :content, :sql_used) RETURNING id"
                ),
                {
                    "conversation_id": conversation_id,
                    "role": role,
                    "content": content,
                    "sql_used": sql_used,
                },
            ).scalar_one()

    def get_history(self, conversation_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the last `limit` messages of a conversation, oldest first."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, role, content, sql_used, created_at "
                    "FROM messages "
                    "WHERE conversation_id = :conversation_id "
                    # Newest first, so LIMIT keeps the most recent messages.
                    # Ordering by id (not created_at) keeps messages saved in the
                    # same instant in the order they were added.
                    "ORDER BY id DESC "
                    "LIMIT :limit"
                ),
                {"conversation_id": conversation_id, "limit": max(limit, 0)},
            ).mappings().all()
        # Flip the list so it reads like a chat: oldest at the top.
        return [dict(row) for row in reversed(rows)]

    def list_conversations(self, user_id: str = "demo") -> List[Dict[str, Any]]:
        """Return this user's conversations, most recently used first.

        A returning user picks one from this list and carries on with its id.
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, title, created_at, last_active_at "
                    "FROM conversations "
                    "WHERE user_id = :user_id "
                    "ORDER BY last_active_at DESC, id DESC"
                ),
                {"user_id": user_id},
            ).mappings().all()
        return [dict(row) for row in rows]

    def build_context(self, conversation_id: int, limit: int = 6) -> str:
        """Return the recent turns as plain text, ready to paste into an AI prompt.

        This is what lets a follow-up like "and by category?" make sense: the AI
        sees the earlier question and the SQL that answered it. Example:

            User: What were total sales last month?
            Assistant: Total sales were $12,340.
            SQL used: SELECT sum(total_amount) FROM orders WHERE ...
        """
        lines = []
        for message in self.get_history(conversation_id, limit=limit):
            speaker = "User" if message["role"] == "user" else "Assistant"
            lines.append("{}: {}".format(speaker, message["content"]))
            if message["sql_used"]:
                lines.append("SQL used: {}".format(message["sql_used"]))
        return "\n".join(lines)


conversation_store = ConversationStore()

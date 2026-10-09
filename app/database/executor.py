"""Run LLM-written SQL safely: validate, then execute read-only with a timeout and row cap."""
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

import psycopg2.errors
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database.connection import engine as default_engine
from app.security.sql_validator import SQLValidator, sql_validator


@dataclass
class QueryResult:
    success: bool
    sql: str
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False  # True when more rows existed than max_rows
    execution_time_ms: float = 0.0
    error: Optional[str] = None
    error_type: Optional[str] = None  # "validation", "timeout" or "database"


class QueryExecutor:
    def __init__(
        self,
        engine: Optional[Engine] = None,
        validator: Optional[SQLValidator] = None,
        max_rows: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self._engine = engine or default_engine
        self._validator = validator or sql_validator
        self.max_rows = settings.max_query_rows if max_rows is None else max_rows
        self.timeout_seconds = (
            settings.query_timeout_seconds if timeout_seconds is None else timeout_seconds
        )

    def execute(self, sql: str) -> QueryResult:
        validation = self._validator.validate(sql)
        if not validation.is_valid:
            return QueryResult(
                success=False, sql=sql, error=validation.error, error_type="validation"
            )

        started = time.perf_counter()
        try:
            with self._engine.connect() as conn:
                try:
                    # Enforced by PostgreSQL itself, whatever the validator let through.
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                    conn.execute(text(
                        "SET LOCAL statement_timeout = {}".format(int(self.timeout_seconds * 1000))
                    ))
                    # exec_driver_sql: run the text as-is, without treating ':name' as a parameter
                    # Not streamed (server-side cursor): that would wrap the SQL in a DECLARE
                    # and make PostgreSQL's error messages point at the wrapper.
                    result = conn.exec_driver_sql(validation.sql.replace("%", "%%"))
                    columns = list(result.keys())
                    fetched = result.fetchmany(self.max_rows + 1)
                    result.close()
                finally:
                    conn.rollback()
        except SQLAlchemyError as exc:
            timed_out = isinstance(getattr(exc, "orig", None), psycopg2.errors.QueryCanceled)
            return QueryResult(
                success=False,
                sql=validation.sql,
                execution_time_ms=self._elapsed_ms(started),
                error=(
                    "Query exceeded the {}s time limit.".format(self.timeout_seconds)
                    if timed_out
                    else str(getattr(exc, "orig", exc)).strip()
                ),
                error_type="timeout" if timed_out else "database",
            )

        rows = [list(row) for row in fetched[: self.max_rows]]
        return QueryResult(
            success=True,
            sql=validation.sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=len(fetched) > self.max_rows,
            execution_time_ms=self._elapsed_ms(started),
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)


query_executor = QueryExecutor()

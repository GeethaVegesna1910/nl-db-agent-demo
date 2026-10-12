"""Decide whether a SQL string is a single read-only query.

This is the first of two safety layers. The second is QueryExecutor, which runs
every query inside a READ ONLY transaction, so anything that slips past these
checks still cannot modify data.
"""
from dataclasses import dataclass
from typing import Optional

import sqlparse
from sqlparse import tokens as T

# Statement-level keywords that change data, schema, permissions or session state.
FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "TRUNCATE",
    "CREATE", "ALTER", "DROP", "RENAME", "COMMENT",
    "GRANT", "REVOKE",
    "COPY", "CALL", "DO", "EXECUTE", "EXEC", "PREPARE", "DEALLOCATE",
    "SET", "RESET", "SHOW", "BEGIN", "START", "COMMIT", "ROLLBACK", "SAVEPOINT",
    "LOCK", "VACUUM", "ANALYZE", "EXPLAIN", "REINDEX", "CLUSTER", "REFRESH",
    "LISTEN", "NOTIFY", "UNLISTEN", "LOAD", "CHECKPOINT", "DISCARD",
    "INTO",  # SELECT ... INTO new_table creates a table
}
# Identifiers that give access to server internals, files or other databases.
FORBIDDEN_NAMES = {
    "information_schema", "dblink", "dblink_exec", "dblink_connect",
    "lo_import", "lo_export", "lo_unlink", "set_config", "current_setting",
    "query_to_xml", "query_to_xml_and_xmlschema", "database_to_xml", "table_to_xml",
    "nextval", "setval",
    "uescape",  # U&"!0070g_sleep" UESCAPE '!' would hide a name behind a custom escape
}
FORBIDDEN_NAME_PREFIXES = ("pg_",)
# Application-private tables (chat history). The agent must never read these.
PRIVATE_TABLES = {"conversations", "messages"}


@dataclass
class ValidationResult:
    is_valid: bool
    sql: str = ""  # cleaned SQL (comments and trailing semicolon removed) when valid
    error: Optional[str] = None


class SQLValidator:
    def validate(self, sql: str) -> ValidationResult:
        if not sql or not sql.strip():
            return self._reject("Query is empty.")

        cleaned = sqlparse.format(sql, strip_comments=True).strip().rstrip(";").strip()
        if not cleaned:
            return self._reject("Query is empty.")

        statements = [s for s in sqlparse.parse(cleaned) if str(s).strip()]
        if len(statements) != 1:
            return self._reject("Only a single SQL statement is allowed.")
        statement = statements[0]

        first = statement.token_first(skip_ws=True, skip_cm=True)
        if first is None or first.normalized.upper() not in ("SELECT", "WITH"):
            return self._reject("Only SELECT queries are allowed (the query must start with SELECT or WITH).")
        if statement.get_type() != "SELECT":
            return self._reject("Only SELECT queries are allowed.")

        for token in statement.flatten():
            if token.ttype in T.Keyword:
                word = token.normalized.upper()
                if word in FORBIDDEN_KEYWORDS or (
                    token.ttype in (T.Keyword.DML, T.Keyword.DDL) and word != "SELECT"
                ):
                    return self._reject("'{}' is not allowed in read-only queries.".format(word))
            if token.ttype in T.Name or token.ttype in T.Keyword or token.ttype in T.Literal.String.Symbol:
                name = token.value.strip('"').lower()
                # U&"\0070g_sleep" spells pg_sleep with Unicode escapes, hiding it from the
                # name checks below. Real identifiers here never contain a backslash.
                if token.ttype in T.Literal.String.Symbol and "\\" in name:
                    return self._reject("Escaped identifiers are not allowed.")
                if (
                    name in FORBIDDEN_NAMES
                    or name in PRIVATE_TABLES
                    or name.startswith(FORBIDDEN_NAME_PREFIXES)
                ):
                    return self._reject("Access to '{}' is not allowed.".format(name))

        return ValidationResult(is_valid=True, sql=cleaned)

    @staticmethod
    def _reject(reason: str) -> ValidationResult:
        return ValidationResult(is_valid=False, error=reason)


sql_validator = SQLValidator()

"""Read the live database schema (tables, columns, keys) so it can be shown to the LLM."""
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.database.connection import engine as default_engine


class SchemaIntrospector:
    def __init__(self, engine: Optional[Engine] = None):
        self._engine = engine or default_engine
        self._cache: Optional[Dict[str, Dict[str, Any]]] = None

    def get_schema(self, refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """Return {table_name: {"columns": [...], "primary_key": [...], "foreign_keys": [...]}}."""
        if self._cache is None or refresh:
            inspector = inspect(self._engine)
            self._cache = {
                table: self._describe_table(inspector, table)
                for table in sorted(inspector.get_table_names())
            }
        return self._cache

    def get_table_names(self) -> List[str]:
        return list(self.get_schema())

    def get_table_schema(self, table_name: str) -> Dict[str, Any]:
        schema = self.get_schema()
        if table_name not in schema:
            raise KeyError("Unknown table: {}".format(table_name))
        return schema[table_name]

    def describe(self) -> str:
        """Compact text rendering of the schema, suitable for an LLM prompt."""
        lines = []
        for table, info in self.get_schema().items():
            lines.append("TABLE {}".format(table))
            for col in info["columns"]:
                notes = []
                if col["name"] in info["primary_key"]:
                    notes.append("primary key")
                if not col["nullable"]:
                    notes.append("not null")
                for fk in info["foreign_keys"]:
                    if col["name"] in fk["columns"]:
                        notes.append("references {}({})".format(
                            fk["referred_table"], ", ".join(fk["referred_columns"])
                        ))
                suffix = "  -- " + ", ".join(notes) if notes else ""
                lines.append("  {} {}{}".format(col["name"], col["type"], suffix))
            for check in info["check_constraints"]:
                lines.append("  CHECK ({})".format(check))
            lines.append("")
        return "\n".join(lines).rstrip()

    @staticmethod
    def _describe_table(inspector, table: str) -> Dict[str, Any]:
        return {
            "columns": [
                {"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]}
                for c in inspector.get_columns(table)
            ],
            "primary_key": inspector.get_pk_constraint(table)["constrained_columns"],
            "foreign_keys": [
                {
                    "columns": fk["constrained_columns"],
                    "referred_table": fk["referred_table"],
                    "referred_columns": fk["referred_columns"],
                }
                for fk in inspector.get_foreign_keys(table)
            ],
            "check_constraints": [
                c["sqltext"] for c in inspector.get_check_constraints(table)
            ],
        }


schema_introspector = SchemaIntrospector()

"""Business definitions (the "semantic layer").

The database schema tells the AI what tables and columns exist. It does not say
what the business MEANS by "revenue" or "top products". Left to guess, the AI
might count cancelled orders one day and skip them the next.

metadata/business_semantics.yaml holds those meanings. This module reads that
file and turns it into a short block of text for the AI prompt, so every
question is answered with the same calculations.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.config import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "metadata" / "business_semantics.yaml"


class SemanticLayer:
    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else DEFAULT_PATH
        self._data: Optional[Dict[str, Any]] = None

    def load(self, refresh: bool = False) -> Dict[str, Any]:
        """Read the YAML file (once; later calls reuse the result)."""
        if self._data is None or refresh:
            # safe_load only builds plain data (dicts, lists, text). It can
            # never run code hidden in the file.
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            # Fail early, with a clear message, if the file is badly formed.
            if not isinstance(data.get("metrics"), dict) or not data["metrics"]:
                raise ValueError("{} must have a 'metrics' section".format(self._path))
            for name, metric in data["metrics"].items():
                for key in ("description", "calculation"):
                    if not metric.get(key):
                        raise ValueError("Metric '{}' is missing '{}'".format(name, key))
            self._data = data
        return self._data

    def get_metric(self, name: str) -> Dict[str, Any]:
        metrics = self.load()["metrics"]
        if name not in metrics:
            raise KeyError("Unknown metric: {}".format(name))
        return metrics[name]

    def describe(self) -> str:
        """Compact text rendering of the definitions, suitable for an LLM prompt."""
        data = self.load()
        lines: List[str] = ["METRICS"]
        for name, metric in data["metrics"].items():
            lines.append("- {}: {}".format(name.replace("_", " "), metric["description"]))
            if metric.get("synonyms"):
                lines.append("  Also called: {}".format(", ".join(metric["synonyms"])))
            calculation = metric["calculation"]
            if metric.get("filter"):
                calculation += "  WHERE {}".format(metric["filter"])
            lines.append("  Calculate as: {}".format(calculation))
            if metric.get("notes"):
                # YAML '>' text can span lines; squeeze it onto one.
                lines.append("  Note: {}".format(" ".join(metric["notes"].split())))

        rules = data.get("rules") or []
        if rules:
            lines.append("")
            lines.append("RULES")
            for number, rule in enumerate(rules, start=1):
                lines.append("{}. {}: {}".format(
                    number, rule["name"].capitalize(), " ".join(rule["rule"].split())
                ))
        return "\n".join(lines)


semantic_layer = SemanticLayer()

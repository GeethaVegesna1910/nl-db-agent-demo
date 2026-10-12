"""Turn raw query results into something a person can read at a glance.

The database gives back columns and rows. ResultFormatter adds four things:

    summary     one plain-English sentence, e.g. "Total revenue is $581,294.51."
    chart       which picture suits the data: "number", "bar", "line" or "table"
    highlights  anything unusual, e.g. one item making up most of the total
    follow_ups  two or three questions the user might want to ask next

Everything here is ordinary Python rules: no AI call, so it is instant, free and
gives the same output for the same rows every time. All values it returns are
plain text, numbers and lists, so the result can be turned into JSON.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

EMPTY_SUMMARY = "No matching rows found."

# --- Thresholds for the rules (change these to tune the behaviour) ---
MAX_CHART_ROWS = 50        # more rows than this is unreadable as a chart
HALF_OF_TOTAL = 0.5        # one item above this share of the total is worth a mention
OUTLIER_TIMES = 2.0        # "far above average" = at least this many times the average
MIN_ROWS_FOR_OUTLIER = 4   # with fewer rows, an average means little
MAX_HIGHLIGHTS = 3
MAX_FOLLOW_UPS = 3

# --- Words in a column name that tell us what the column holds ---
# Names are split on "_" first, so "total_revenue" gives the words total + revenue.
MONEY_WORDS = {
    "revenue", "sales", "amount", "price", "cost", "value", "spend", "spent",
    "profit", "turnover", "income", "earnings", "aov", "margin",
}
NOT_MONEY_WORDS = {
    "quantity", "qty", "count", "units", "number", "num", "percent", "pct",
    "share", "rate", "stock", "orders", "customers", "items", "products",
}
# Averages and prices cannot be added up, so "% of the total" makes no sense for them.
NOT_ADDABLE_WORDS = {
    "avg", "average", "mean", "median", "min", "max", "price", "cost", "rate",
    "percent", "pct", "share", "aov",
}
TIME_WORDS = {"year", "month", "quarter", "week", "day", "date"}
# Names PostgreSQL or the AI give a column when nothing better was chosen.
VAGUE_NAMES = {"sum": "the total", "avg": "the average", "count": "the count",
               "total": "the total", "max": "the highest value", "min": "the lowest value",
               "?column?": "the result", "value": "the value", "result": "the result"}
VAGUE_LABELS = {"name", "title", "label", "item"}

# Ways to slice the data that this shop's tables support, in the order we suggest them.
SALES_DIMENSIONS = ["category", "country", "month", "state", "product"]
CUSTOMER_DIMENSIONS = ["state", "city", "country"]
ORDER_DIMENSIONS = ["status", "month", "country"]

ISO_DATE_TEXT = re.compile(r"\d{4}-\d{2}(-\d{2})?$")  # "2026-10" or "2026-10-09"


def json_safe(value: Any) -> Any:
    """Convert database values into ones json.dumps accepts.

    Decimal -> int or float, dates -> "2026-10-09" text, lists handled item by item.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)  # anything unusual (UUID, timedelta, ...) becomes text


def is_number(value: Any) -> bool:
    # bool is technically a number in Python, but True/False is not a measurement.
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def words_in(name: str) -> set:
    """'Total_Revenue' -> {'total', 'revenue'}"""
    return set(re.split(r"[^a-z0-9?]+", name.lower())) - {""}


@dataclass
class Column:
    """What we worked out about one column of the result."""
    index: int
    name: str
    kind: str            # "number", "date", "text", "id" or "empty"
    values: List[Any]    # this column's value from every row (may contain None)
    is_money: bool = False

    @property
    def label(self) -> str:
        """Readable name: 'total_revenue' -> 'total revenue'."""
        if self.name.lower() in VAGUE_NAMES:
            return VAGUE_NAMES[self.name.lower()]
        return self.name.replace("_", " ").strip().lower() or "value"

    @property
    def can_be_added_up(self) -> bool:
        return not (words_in(self.name) & NOT_ADDABLE_WORDS)


class ResultFormatter:
    def format(
        self,
        question: str,
        sql: Optional[str],
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> Dict[str, Any]:
        """Return {"summary", "chart", "highlights", "follow_ups"} for a query result."""
        question = question or ""
        columns = list(columns or [])
        rows = [list(row) for row in (rows or [])]

        # Nothing came back. A query like SELECT SUM(...) over zero rows returns
        # one row holding only None, which means the same thing to the user.
        if not columns or not rows or all(cell is None for row in rows for cell in row):
            return {
                "summary": EMPTY_SUMMARY,
                "chart": "table",
                "highlights": [],
                "follow_ups": ["What is the total revenue?", "How many orders are there?"],
            }

        profile = self._profile(columns, rows, question)
        numbers = [c for c in profile if c.kind == "number"]
        dates = [c for c in profile if c.kind == "date"]
        texts = [c for c in profile if c.kind == "text"]
        ids = [c for c in profile if c.kind == "id"]
        measure = self._main_measure(numbers)
        has_limit = bool(sql and re.search(r"\blimit\s+\d+", sql, re.IGNORECASE))

        # ---- Chart: simple rules, checked in order ----
        label: Optional[Column] = None
        if len(rows) == 1:
            # A single value (optionally with a name next to it).
            chart = "number" if len(numbers) == 1 else "table"
            label = (texts or dates or [None])[0]
        elif not numbers or len(rows) > MAX_CHART_ROWS:
            chart = "table"
        elif dates and not texts:
            chart, label = "line", dates[0]      # a date plus a number
        elif texts and not dates:
            chart, label = "bar", texts[0]       # a category plus a number
        elif ids and not texts and not dates:
            chart, label = "bar", ids[0]         # e.g. customer_id plus a number
        else:
            chart = "table"                      # anything more complicated

        # ---- Summary, highlights and follow-ups depend on the chart ----
        if len(rows) == 1:
            summary = self._summarise_one_row(profile, numbers, label)
            highlights: List[str] = []
        elif chart == "bar":
            summary = self._summarise_groups(rows, label, measure, has_limit)
            highlights = self._highlight_groups(rows, label, measure, has_limit)
        elif chart == "line":
            summary = self._summarise_trend(rows, label, measure)
            highlights = self._highlight_outliers(rows, label, measure, skip=set())
        else:
            summary = "Found {} rows with {}.".format(
                self._number(len(rows)), self._join([c.label for c in profile][:5])
            )
            highlights = []

        if chart in ("bar", "line") and measure is not None:
            missing = sum(1 for value in measure.values if value is None)
            if missing:
                highlights.append("{} row{} have no value for {}.".format(
                    missing, "" if missing == 1 else "s", measure.label
                ).replace("1 row have", "1 row has"))

        return {
            "summary": summary,
            "chart": chart,
            "highlights": highlights[:MAX_HIGHLIGHTS],
            "follow_ups": self._follow_ups(question, profile, chart, len(rows), has_limit, measure),
        }

    # ------------------------------------------------------------------
    # Step 1: look at each column and decide what kind of data it holds
    # ------------------------------------------------------------------
    def _profile(self, columns: List[str], rows: List[List[Any]], question: str) -> List[Column]:
        question_is_about_money = bool(words_in(question) & MONEY_WORDS)
        profile = []
        for index, name in enumerate(columns):
            values = [row[index] if index < len(row) else None for row in rows]
            present = [v for v in values if v is not None]  # None tells us nothing
            words = words_in(name)

            if not present:
                kind = "empty"
            elif all(isinstance(v, (date, datetime)) for v in present):
                kind = "date"
            elif all(is_number(v) for v in present):
                if "id" in words:
                    kind = "id"        # 42 in customer_id is a name tag, not an amount
                elif words & TIME_WORDS and not words & (MONEY_WORDS | NOT_MONEY_WORDS):
                    kind = "date"      # e.g. a "year" column holding 2025, 2026
                else:
                    kind = "number"
            elif all(isinstance(v, str) and ISO_DATE_TEXT.match(v) for v in present):
                kind = "date"          # dates the query turned into text, like "2026-10"
            else:
                kind = "text"

            is_money = False
            if kind == "number":
                if words & NOT_MONEY_WORDS:
                    is_money = False
                elif words & MONEY_WORDS:
                    is_money = True
                elif name.lower() in VAGUE_NAMES and name.lower() != "count":
                    # A column just called "sum": fall back on the question's wording.
                    is_money = question_is_about_money
            profile.append(Column(index, name, kind, values, is_money))
        return profile

    @staticmethod
    def _main_measure(numbers: List[Column]) -> Optional[Column]:
        """Pick the number column the result is 'about'."""
        if not numbers:
            return None
        # Results are usually sorted by the number that matters (highest first).
        for column in numbers:
            present = [float(v) for v in column.values if v is not None]
            if len(present) > 1 and present == sorted(present, reverse=True) and present[0] != present[-1]:
                return column
        for column in numbers:
            if column.is_money:
                return column
        return numbers[0]

    # ------------------------------------------------------------------
    # Step 2: write the summary sentence
    # ------------------------------------------------------------------
    def _summarise_one_row(self, profile, numbers, label) -> str:
        if not numbers:
            return "Found 1 row with {}.".format(self._join([c.label for c in profile][:5]))
        parts = [
            "{} is {}".format(c.label, self._value(c.values[0], c)) for c in numbers[:3]
        ]
        if label is not None and label.values[0] is not None:
            if len(numbers) == 1:
                # "USA has revenue of $581,294.51."
                only = numbers[0]
                return "{} has {} of {}.".format(
                    self._label_text(label.values[0], label),
                    re.sub(r"^the ", "a ", only.label),
                    self._value(only.values[0], only),
                )
            return "For {}, {}.".format(self._label_text(label.values[0], label), self._join(parts))
        sentence = self._join(parts) + "."
        return sentence[0].upper() + sentence[1:]

    def _summarise_groups(self, rows, label: Column, measure: Column, has_limit: bool) -> str:
        """'USA is the top country by revenue with $345,000 (28% of the total).'"""
        pairs = self._pairs(label, measure)
        if not pairs:
            return "Found {} rows.".format(self._number(len(rows)))
        top_label, top_value = max(pairs, key=lambda pair: pair[1])
        noun = "result" if label.label in VAGUE_LABELS else label.label
        sentence = "{} is the top {} by {} with {}".format(
            self._label_text(top_label, label), noun,
            re.sub(r"^the ", "", measure.label), self._value(top_value, measure),
        )
        share = self._share(top_value, pairs, measure)
        # With a LIMIT (a "top 5") we only see some of the rows, so a share of
        # "the total" would be wrong. Leave it out.
        if share is not None and not has_limit:
            sentence += " ({} of the total)".format(self._percent(share))
        return sentence + "."

    def _summarise_trend(self, rows, label: Column, measure: Column) -> str:
        """'Across 24 periods from Oct 2024 to Oct 2026, revenue peaked at $31,200 (Dec 2025).'"""
        pairs = sorted(self._pairs(label, measure), key=lambda pair: pair[0])
        if not pairs:
            return "Found {} rows.".format(self._number(len(rows)))
        peak_label, peak_value = max(pairs, key=lambda pair: pair[1])
        return "Across {} periods from {} to {}, {} peaked at {} ({}).".format(
            self._number(len(pairs)),
            self._label_text(pairs[0][0], label), self._label_text(pairs[-1][0], label),
            measure.label, self._value(peak_value, measure), self._label_text(peak_label, label),
        )

    # ------------------------------------------------------------------
    # Step 3: look for anything unusual
    # ------------------------------------------------------------------
    def _highlight_groups(self, rows, label: Column, measure: Column, has_limit: bool) -> List[str]:
        highlights, mentioned = [], set()
        pairs = self._pairs(label, measure)
        if pairs:
            top_label, top_value = max(pairs, key=lambda pair: pair[1])
            share = self._share(top_value, pairs, measure)
            if share is not None and share > HALF_OF_TOTAL and not has_limit:
                highlights.append("{} makes up {} of the total, more than everything else combined.".format(
                    self._label_text(top_label, label), self._percent(share),
                ))
                mentioned.add(top_label)
        return highlights + self._highlight_outliers(rows, label, measure, skip=mentioned)

    def _highlight_outliers(self, rows, label: Column, measure: Column, skip: set) -> List[str]:
        """Values at least OUTLIER_TIMES the average."""
        pairs = self._pairs(label, measure)
        if len(pairs) < MIN_ROWS_FOR_OUTLIER:
            return []
        average = sum(value for _, value in pairs) / len(pairs)
        if average <= 0:
            return []
        highlights = []
        for item, value in sorted(pairs, key=lambda pair: pair[1], reverse=True):
            if value >= OUTLIER_TIMES * average and item not in skip:
                highlights.append("{} ({}) is {:.1f} times the average of {}.".format(
                    self._label_text(item, label), self._value(value, measure),
                    value / average, self._value(average, measure),
                ))
        return highlights[:2]

    # ------------------------------------------------------------------
    # Step 4: suggest what to ask next
    # ------------------------------------------------------------------
    @staticmethod
    def _follow_ups(question, profile, chart, row_count, has_limit, measure) -> List[str]:
        names = " ".join(c.name.lower() for c in profile)
        topic = names + " " + question.lower()
        about_money = measure is not None and measure.is_money
        about_customers = "customer" in topic and not about_money
        if about_customers:
            dimensions = CUSTOMER_DIMENSIONS
        elif "order" in topic and not about_money and "product" not in topic:
            dimensions = ORDER_DIMENSIONS    # counting orders: status is the natural split
        else:
            dimensions = SALES_DIMENSIONS
        # Don't suggest a breakdown the user is already looking at.
        shown = {c.label for c in profile} | set(words_in(names))
        if any(c.kind == "date" for c in profile):
            shown.add("month")
        if "name" in shown and not about_customers:
            shown.add("product")
        unused = [d for d in dimensions if d not in shown]

        ideas: List[str] = []
        if chart == "bar":
            if unused:
                ideas.append("Show it by {} instead".format(unused[0]))
            if row_count > 5 and not has_limit:
                ideas.append("What are the top 5?")
            elif has_limit:
                ideas.append("Show all of them, not just the top ones")
            if "month" in unused[1:]:
                ideas.append("How has it changed by month?")
            elif len(unused) > 1:
                ideas.append("Show it by {} instead".format(unused[1]))
        elif chart == "line":
            ideas.append("Which period was the highest?")
            ideas += ["Show it by {} instead".format(d) for d in unused[:2]]
        elif chart == "number" or (row_count == 1 and measure is not None):
            ideas += ["Break it down by {}".format(d) for d in unused[:2]]
            if "month" in unused[2:]:
                ideas.append("How has it changed by month?")
        else:
            ideas.append("How many are there in total?")
            if row_count > 10:
                ideas.append("Show only the first 10")
            if measure is not None:
                ideas.append("Which has the highest {}?".format(re.sub(r"^the ", "", measure.label)))

        # Always offer at least two.
        for spare in ("What is the total revenue?", "What are the top 5 products?"):
            if len(ideas) < 2:
                ideas.append(spare)
        return ideas[:MAX_FOLLOW_UPS]

    # ------------------------------------------------------------------
    # Small helpers: numbers, dates and lists as readable text
    # ------------------------------------------------------------------
    @staticmethod
    def _pairs(label: Column, measure: Optional[Column]) -> list:
        """(label, number) for every row that has both."""
        if measure is None:
            return []
        return [
            (name, float(value))
            for name, value in zip(label.values, measure.values)
            if name is not None and value is not None
        ]

    @staticmethod
    def _share(value: float, pairs: list, measure: Column) -> Optional[float]:
        """value as a fraction of the column total, when that is meaningful."""
        total = sum(v for _, v in pairs)
        if not measure.can_be_added_up or total <= 0 or any(v < 0 for _, v in pairs):
            return None
        return value / total

    @staticmethod
    def _percent(fraction: float) -> str:
        percent = round(fraction * 100)
        if percent == 0 and fraction > 0:
            return "less than 1%"
        return "{}%".format(percent)

    @staticmethod
    def _number(value: Any, money: bool = False) -> str:
        """1234567.5 -> '1,234,567.5', or '$1,234,567.50' for money."""
        if value is None:
            return "no value"
        number = float(value)
        whole = number == int(number)
        if money:
            text = "{:,.0f}".format(abs(number)) if whole else "{:,.2f}".format(abs(number))
            return ("-$" if number < 0 else "$") + text
        if whole:
            return "{:,}".format(int(number))
        return "{:,.2f}".format(number).rstrip("0").rstrip(".")

    def _value(self, value: Any, column: Column) -> str:
        return self._number(value, money=column.is_money)

    @staticmethod
    def _label_text(value: Any, column: Column) -> str:
        """A label as text; dates become '2026-10-09', or 'Oct 2026' for monthly data."""
        if isinstance(value, (date, datetime)):
            present = [v for v in column.values if v is not None]
            if len(present) > 1 and all(v.day == 1 for v in present):
                return value.strftime("%b %Y")
            if isinstance(value, datetime) and (value.hour or value.minute or value.second):
                return value.strftime("%Y-%m-%d %H:%M")
            return value.strftime("%Y-%m-%d")
        return str(value)

    @staticmethod
    def _join(items: List[str]) -> str:
        """['a', 'b', 'c'] -> 'a, b and c'"""
        if len(items) <= 1:
            return "".join(items)
        return "{} and {}".format(", ".join(items[:-1]), items[-1])


result_formatter = ResultFormatter()

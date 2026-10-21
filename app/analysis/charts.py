from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analysis.tools import TableResult

MAX_POINTS = 500
MAX_BARS = 30


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["bar", "line"]
    title: str = Field(max_length=200)
    x_label: str = Field(max_length=200)
    y_label: str = Field(max_length=200)
    x: list[str] = Field(min_length=1, max_length=MAX_POINTS)
    y: list[float | None] = Field(min_length=1, max_length=MAX_POINTS)

    @model_validator(mode="after")
    def same_length(self):
        if len(self.x) != len(self.y):
            raise ValueError("x and y must have the same length")
        return self


def chart_for(tool: str, title: str, table: TableResult) -> ChartSpec | None:
    if not table.rows:
        return None
    if tool == "analyze_time_trend":
        return _spec("line", title, table.columns[0], table.columns[1], table.rows, MAX_POINTS)
    if tool in ("aggregate_data", "get_top_n") and len(table.columns) >= 2:
        labels = [[" / ".join(str(v) for v in row[:-1]), row[-1]] for row in table.rows]
        return _spec("bar", title, " / ".join(table.columns[:-1]), table.columns[-1], labels, MAX_BARS)
    if tool == "compute_correlation":
        pairs = [[f"{a} × {b}", value] for a, b, value, _ in table.rows]
        return _spec("bar", title, "column pair", "correlation", pairs, MAX_BARS)
    return None


def _spec(kind: str, title: str, x_label: str, y_label: str, rows: list[list], limit: int) -> ChartSpec | None:
    if len(rows) > limit:
        title = f"{title} (first {limit})"
        rows = rows[:limit]
    values = [row[1] for row in rows]
    if not any(_is_number(v) for v in values) or not all(v is None or _is_number(v) for v in values):
        return None
    return ChartSpec(
        type=kind,
        title=title,
        x_label=x_label,
        y_label=y_label,
        x=[str(row[0]) for row in rows],
        y=values,
    )


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

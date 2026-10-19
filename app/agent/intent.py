import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.analysis.tools import AggregateArgs, CorrelationArgs, FilterArgs, TopNArgs, TrendArgs


class IntentError(ValueError):
    pass


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileIntent(Strict):
    tool: Literal["profile_dataset"]


class ListColumnsIntent(Strict):
    tool: Literal["list_columns"]


class AggregateIntent(AggregateArgs, Strict):
    tool: Literal["aggregate_data"]


class TopNIntent(TopNArgs, Strict):
    tool: Literal["get_top_n"]


class FilterIntent(FilterArgs, Strict):
    tool: Literal["filter_data"]


class CorrelationIntent(CorrelationArgs, Strict):
    tool: Literal["compute_correlation"]


class TrendIntent(TrendArgs, Strict):
    tool: Literal["analyze_time_trend"]


class ClarifyIntent(Strict):
    tool: Literal["clarify"]
    question: str = Field(min_length=1, max_length=300)


class UnsupportedIntent(Strict):
    tool: Literal["unsupported"]
    reason: str = Field(min_length=1, max_length=300)


Intent = Annotated[
    Union[
        ProfileIntent,
        ListColumnsIntent,
        AggregateIntent,
        TopNIntent,
        FilterIntent,
        CorrelationIntent,
        TrendIntent,
        ClarifyIntent,
        UnsupportedIntent,
    ],
    Field(discriminator="tool"),
]


class IntentEnvelope(BaseModel):
    intent: Intent


def parse_intent(text: str) -> Intent:
    try:
        data = json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        raise IntentError("The model did not return valid JSON.") from None
    try:
        return IntentEnvelope.model_validate({"intent": _unwrap_arguments(data)}).intent
    except ValidationError as error:
        raise IntentError(f"The model returned an invalid plan: {_describe(error)}") from None


def referenced_columns(intent: Intent) -> list[str]:
    columns = []
    for field in ("column", "date_column"):
        if value := getattr(intent, field, None):
            columns.append(value)
    group_by = getattr(intent, "group_by", [])
    columns += [group_by] if isinstance(group_by, str) else group_by
    columns += getattr(intent, "columns", [])
    columns += [c.column for c in getattr(intent, "filters", []) + getattr(intent, "conditions", [])]
    return list(dict.fromkeys(columns))


def check_columns(intent: Intent, available: list[str]) -> None:
    unknown = [c for c in referenced_columns(intent) if c not in available]
    if unknown:
        raise IntentError(f"The plan uses columns that are not in the dataset: {', '.join(unknown)}.")


def _unwrap_arguments(data: Any) -> Any:
    if isinstance(data, dict) and set(data) == {"tool", "arguments"} and isinstance(data["arguments"], dict):
        return {**data["arguments"], "tool": data["tool"]}
    return data


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _describe(error: ValidationError) -> str:
    problems = []
    for item in error.errors()[:3]:
        location = ".".join(str(part) for part in item["loc"][1:] if not isinstance(part, int))
        problems.append(f"{location or 'tool'}: {item['msg']}")
    return "; ".join(problems)

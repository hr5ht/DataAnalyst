from collections.abc import Callable

import pandas as pd
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agent.explainer import ExplanationError, explain_result
from app.agent.intent import (
    AggregateIntent,
    ClarifyIntent,
    CorrelationIntent,
    FilterIntent,
    Intent,
    IntentError,
    TopNIntent,
    TrendIntent,
    UnsupportedIntent,
)
from app.agent.planner import clean_question, plan_question
from app.agent.state import AnalysisContext, AnalysisState
from app.analysis import tools
from app.analysis.profiler import DatasetProfile, profile_dataset
from app.llm import LLMError
from app.retrieval.glossary import Definition, GlossaryError

MAX_PLAN_ATTEMPTS = 2
TOOLS = {
    "profile_dataset": lambda df, _: profile_dataset(df),
    "list_columns": lambda df, _: tools.list_columns(df),
    "aggregate_data": tools.aggregate_data,
    "get_top_n": tools.get_top_n,
    "filter_data": tools.filter_data,
    "compute_correlation": tools.compute_correlation,
    "analyze_time_trend": tools.analyze_time_trend,
}


def validate(state: AnalysisState, runtime: Runtime[AnalysisContext]) -> AnalysisState:
    if runtime.context.df.empty:
        return {"error": "The dataset has no rows to analyze."}
    try:
        return {"question": clean_question(state.get("question", ""))}
    except IntentError as error:
        return {"error": str(error)}


def retrieve(state: AnalysisState, runtime: Runtime[AnalysisContext]) -> AnalysisState:
    search = runtime.context.search_glossary
    if search is None:
        return {"definitions": []}
    try:
        return {"definitions": search(state["question"], [str(c) for c in runtime.context.df.columns])}
    except GlossaryError as error:
        return {"definitions": [], "warnings": [f"Glossary definitions were not used: {error}"]}


def understand(state: AnalysisState, runtime: Runtime[AnalysisContext]) -> AnalysisState:
    attempts = state.get("attempts", 0) + 1
    try:
        intent = plan_question(
            runtime.context.model,
            state["question"],
            runtime.context.df,
            state.get("definitions", []),
            state.get("feedback"),
        )
    except LLMError as error:
        return {"error": str(error), "provider_error": True, "attempts": attempts}
    except IntentError as error:
        return _retry_or_fail(str(error), attempts)
    return {"intent": intent, "feedback": None, "attempts": attempts}


def execute(state: AnalysisState, runtime: Runtime[AnalysisContext]) -> AnalysisState:
    intent = state["intent"]
    try:
        result = TOOLS[intent.tool](runtime.context.df, intent)
    except tools.AnalysisError as error:
        return _retry_or_fail(f"{intent.tool} failed: {error}", state["attempts"])
    return {"result": result, "warnings": getattr(result, "warnings", [])}


def check(state: AnalysisState) -> AnalysisState:
    intent, result = state["intent"], state.get("result")
    expected = DatasetProfile if intent.tool == "profile_dataset" else tools.TableResult
    if not isinstance(result, expected):
        return {"error": f"{intent.tool} did not return a result."}
    if isinstance(result, tools.TableResult):
        if len(result.rows) > tools.MAX_RESULT_ROWS or any(len(row) != len(result.columns) for row in result.rows):
            return {"error": f"{intent.tool} returned a malformed table."}
        if not result.rows:
            return {"empty": True}
    return {}


def explain(state: AnalysisState, runtime: Runtime[AnalysisContext]) -> AnalysisState:
    intent, result = state["intent"], state["result"]
    if isinstance(result, DatasetProfile):
        return {"answer": summarize_profile(result)}
    if intent.tool == "list_columns":
        return {"answer": f"The dataset has {len(result.rows)} columns."}
    try:
        return {"answer": explain_result(runtime.context.model, state["question"], describe(intent), result)}
    except (ExplanationError, LLMError) as error:
        return {"answer": f"{describe(intent)}.", "warnings": [f"Showing the result without a written summary. {error}"]}


def format_response(state: AnalysisState) -> AnalysisState:
    if "error" in state:
        return {"status": "error", "message": state["error"]}
    intent = state["intent"]
    if isinstance(intent, ClarifyIntent):
        return {"status": "clarify", "message": intent.question}
    if isinstance(intent, UnsupportedIntent):
        return {"status": "unsupported", "message": intent.reason}
    if state.get("empty"):
        return {"status": "empty", "message": "No rows matched, so there is nothing to show."}
    return {"status": "answered", "message": state["answer"]}


def after_validate(state: AnalysisState) -> str:
    return "format" if "error" in state else "retrieve"


def after_understand(state: AnalysisState) -> str:
    if "error" in state:
        return "format"
    if state.get("intent") is None:
        return "understand"
    return "format" if state["intent"].tool in ("clarify", "unsupported") else "execute"


def after_execute(state: AnalysisState) -> str:
    if "error" in state:
        return "format"
    return "understand" if state.get("intent") is None else "check"


def after_check(state: AnalysisState) -> str:
    return "format" if "error" in state or state.get("empty") else "explain"


def describe(intent: Intent) -> str:
    if isinstance(intent, AggregateIntent):
        text = _metric(intent.operation, intent.column)
        return _sentence(f"{text} by {', '.join(intent.group_by)}" if intent.group_by else text)
    if isinstance(intent, TopNIntent):
        side = "Top" if intent.sort == "desc" else "Bottom"
        return f"{side} {intent.n} {intent.group_by} by {_metric(intent.operation, intent.column)}"
    if isinstance(intent, FilterIntent):
        return f"Rows matching {len(intent.conditions)} condition(s)"
    if isinstance(intent, CorrelationIntent):
        return f"{intent.method.title()} correlation between {', '.join(intent.columns)}"
    if isinstance(intent, TrendIntent):
        return _sentence(f"{_metric(intent.operation, intent.column)} per {intent.interval} of {intent.date_column}")
    if intent.tool == "profile_dataset":
        return "Dataset profile"
    return "Columns and their types"


def operation_steps(intent: Intent) -> list[str]:
    steps = [f"filter rows where {_condition(c)}" for c in getattr(intent, "filters", [])]
    metric = "count rows" if getattr(intent, "column", None) is None else f"{intent.operation}({intent.column})"
    if isinstance(intent, AggregateIntent):
        if intent.group_by:
            steps.append(f"group by {', '.join(intent.group_by)}")
        steps.append(metric)
        if intent.group_by and intent.sort:
            steps.append(f"sort {'descending' if intent.sort == 'desc' else 'ascending'}")
    elif isinstance(intent, TopNIntent):
        steps += [f"group by {intent.group_by}", metric, f"keep the {'top' if intent.sort == 'desc' else 'bottom'} {intent.n}"]
    elif isinstance(intent, FilterIntent):
        steps += [f"keep rows where {_condition(c)}" for c in intent.conditions]
        steps.append(f"show {', '.join(intent.columns) if intent.columns else 'all columns'}, up to {intent.limit} rows")
    elif isinstance(intent, CorrelationIntent):
        steps.append(f"{intent.method} correlation of {', '.join(intent.columns)}")
    elif isinstance(intent, TrendIntent):
        if intent.start or intent.end:
            steps.append(f"keep {intent.date_column} from {intent.start or 'the start'} to {intent.end or 'the end'}")
        steps += [f"group {intent.date_column} by {intent.interval}", metric]
    elif intent.tool == "profile_dataset":
        steps.append("profile every column")
    else:
        steps.append("list columns and types")
    return steps


OPERATOR_TEXT = {
    "eq": "=",
    "ne": "≠",
    "gt": ">",
    "gte": "≥",
    "lt": "<",
    "lte": "≤",
    "in": "is one of",
    "contains": "contains",
    "is_null": "is missing",
    "not_null": "is not missing",
}


def _condition(condition: tools.Condition) -> str:
    text = f"{condition.column} {OPERATOR_TEXT[condition.operator]}"
    if condition.operator in ("is_null", "not_null"):
        return text
    value = ", ".join(map(str, condition.value)) if isinstance(condition.value, list) else condition.value
    return f"{text} {value}"


def summarize_profile(profile: DatasetProfile) -> str:
    missing = [c.name for c in profile.column_profiles if c.missing]
    text = f"The dataset has {profile.rows} rows and {profile.columns} columns"
    duplicates = profile.duplicate_rows
    text += f", with {duplicates} duplicate row{'' if duplicates == 1 else 's'}." if duplicates else " and no duplicate rows."
    if missing:
        text += f" Missing values appear in {', '.join(missing[:5])}{' and others' if len(missing) > 5 else ''}."
    return text


def _retry_or_fail(problem: str, attempts: int) -> AnalysisState:
    if attempts < MAX_PLAN_ATTEMPTS:
        return {"intent": None, "feedback": problem, "attempts": attempts}
    return {"error": problem, "attempts": attempts}


def _metric(operation: str, column: str | None) -> str:
    return "row count" if column is None else f"{operation} of {column}"


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def build_graph():
    graph = StateGraph(AnalysisState, context_schema=AnalysisContext)
    graph.add_node("validate", validate)
    graph.add_node("retrieve", retrieve)
    graph.add_node("understand", understand)
    graph.add_node("execute", execute)
    graph.add_node("check", check)
    graph.add_node("explain", explain)
    graph.add_node("format", format_response)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", after_validate, ["retrieve", "format"])
    graph.add_edge("retrieve", "understand")
    graph.add_conditional_edges("understand", after_understand, ["understand", "execute", "format"])
    graph.add_conditional_edges("execute", after_execute, ["understand", "check", "format"])
    graph.add_conditional_edges("check", after_check, ["explain", "format"])
    graph.add_edge("explain", "format")
    graph.add_edge("format", END)
    return graph.compile()


GRAPH = build_graph()


def run_analysis(
    question: str,
    df: pd.DataFrame,
    model: BaseChatModel,
    search_glossary: Callable[[str, list[str]], list[Definition]] | None = None,
) -> AnalysisState:
    context = AnalysisContext(df=df, model=model, search_glossary=search_glossary)
    return GRAPH.invoke({"question": question, "warnings": []}, context=context)

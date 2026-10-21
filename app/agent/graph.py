import pandas as pd
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

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
from app.analysis.profiler import profile_dataset
from app.llm import LLMError

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


def understand(state: AnalysisState, runtime: Runtime[AnalysisContext]) -> AnalysisState:
    try:
        return {"intent": plan_question(runtime.context.model, state["question"], runtime.context.df)}
    except (IntentError, LLMError) as error:
        return {"error": str(error)}


def execute(state: AnalysisState, runtime: Runtime[AnalysisContext]) -> AnalysisState:
    intent = state["intent"]
    try:
        return {"result": TOOLS[intent.tool](runtime.context.df, intent)}
    except tools.AnalysisError as error:
        return {"error": str(error)}


def format_response(state: AnalysisState) -> AnalysisState:
    if "error" in state:
        return {"status": "error", "message": state["error"]}
    intent = state["intent"]
    if isinstance(intent, ClarifyIntent):
        return {"status": "clarify", "message": intent.question}
    if isinstance(intent, UnsupportedIntent):
        return {"status": "unsupported", "message": intent.reason}
    return {"status": "answered", "message": describe(intent)}


def after_validate(state: AnalysisState) -> str:
    return "format" if "error" in state else "understand"


def after_understand(state: AnalysisState) -> str:
    if "error" in state or state["intent"].tool in ("clarify", "unsupported"):
        return "format"
    return "execute"


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


def _metric(operation: str, column: str | None) -> str:
    return "row count" if column is None else f"{operation} of {column}"


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def build_graph():
    graph = StateGraph(AnalysisState, context_schema=AnalysisContext)
    graph.add_node("validate", validate)
    graph.add_node("understand", understand)
    graph.add_node("execute", execute)
    graph.add_node("format", format_response)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", after_validate, ["understand", "format"])
    graph.add_conditional_edges("understand", after_understand, ["execute", "format"])
    graph.add_edge("execute", "format")
    graph.add_edge("format", END)
    return graph.compile()


GRAPH = build_graph()


def run_analysis(question: str, df: pd.DataFrame, model: BaseChatModel) -> AnalysisState:
    return GRAPH.invoke({"question": question}, context=AnalysisContext(df=df, model=model))

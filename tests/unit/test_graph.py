import json

import groq
import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.agent.graph import GRAPH, describe, run_analysis
from app.agent.intent import parse_intent
from app.agent.state import AnalysisContext
from app.analysis.profiler import DatasetProfile


class FailingModel(FakeListChatModel):
    def invoke(self, *args, **kwargs):
        request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        raise groq.APITimeoutError(request=request)


def model(plan):
    return FakeListChatModel(responses=[json.dumps(plan)])


def visited(question, df, chat_model):
    context = AnalysisContext(df=df, model=chat_model)
    return [node for step in GRAPH.stream({"question": question}, context=context) for node in step]


def test_supported_question_runs_end_to_end(orders):
    plan = {"tool": "aggregate_data", "operation": "sum", "column": "amount", "group_by": ["country"]}
    state = run_analysis("Which country spent the most?", orders, model(plan))
    assert state["status"] == "answered"
    assert state["message"] == "Sum of amount by country"
    assert state["intent"].tool == "aggregate_data"
    assert state["result"].columns == ["country", "sum_amount"]
    assert state["result"].rows == [["UK", 110.5], ["France", 20.0], ["Germany", 7.25]]
    assert visited("Which country spent the most?", orders, model(plan)) == [
        "validate",
        "understand",
        "execute",
        "format",
    ]


def test_profile_question_returns_the_profile(orders):
    state = run_analysis("Give me an overview", orders, model({"tool": "profile_dataset"}))
    assert state["status"] == "answered"
    assert isinstance(state["result"], DatasetProfile)
    assert state["result"].rows == 6


@pytest.mark.parametrize(
    ("plan", "status", "message"),
    [
        ({"tool": "clarify", "question": "Amount or quantity?"}, "clarify", "Amount or quantity?"),
        ({"tool": "unsupported", "reason": "Forecasts are not available."}, "unsupported", "Forecasts are not available."),
    ],
)
def test_clarify_and_unsupported_skip_execution(orders, plan, status, message):
    state = run_analysis("Which country is best?", orders, model(plan))
    assert (state["status"], state["message"]) == (status, message)
    assert "result" not in state
    assert visited("Which country is best?", orders, model(plan)) == ["validate", "understand", "format"]


def test_blank_question_stops_before_the_model(orders):
    chat_model = model({"tool": "list_columns"})
    state = run_analysis("   ", orders, chat_model)
    assert state["status"] == "error"
    assert state["message"] == "Ask a question about the dataset."
    assert chat_model.i == 0
    assert visited("   ", orders, model({"tool": "list_columns"})) == ["validate", "format"]


def test_empty_dataset_is_rejected(orders):
    state = run_analysis("How many rows?", orders.iloc[0:0], model({"tool": "profile_dataset"}))
    assert state["status"] == "error"
    assert "no rows" in state["message"]


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        ({"tool": "aggregate_data", "operation": "sum", "column": "profit"}, "not in the dataset: profit"),
        ({"tool": "aggregate_data", "operation": "sum", "column": "country"}, "numeric"),
        ({"tool": "run_python", "code": "print(1)"}, "invalid plan"),
    ],
)
def test_bad_plans_end_as_errors(orders, plan, message):
    state = run_analysis("Total?", orders, model(plan))
    assert state["status"] == "error"
    assert message in state["message"]
    assert "result" not in state


def test_provider_failure_ends_as_an_error(orders):
    state = run_analysis("Total amount?", orders, FailingModel(responses=[]))
    assert state["status"] == "error"
    assert state["message"] == "The LLM took too long to respond. Try again."


@pytest.mark.parametrize(
    ("plan", "text"),
    [
        ({"tool": "list_columns"}, "Columns and their types"),
        ({"tool": "aggregate_data", "operation": "count"}, "Row count"),
        ({"tool": "get_top_n", "group_by": "Country", "column": "Revenue", "n": 3}, "Top 3 Country by sum of Revenue"),
        ({"tool": "get_top_n", "group_by": "country", "sort": "asc"}, "Bottom 10 country by row count"),
        ({"tool": "filter_data", "conditions": [{"column": "qty", "operator": "gt", "value": 1}]}, "Rows matching 1 condition(s)"),
        ({"tool": "compute_correlation", "columns": ["amount", "qty"]}, "Pearson correlation between amount, qty"),
        ({"tool": "analyze_time_trend", "date_column": "ordered_at", "column": "amount"}, "Sum of amount per month of ordered_at"),
    ],
)
def test_answers_describe_the_step_that_ran(plan, text):
    assert describe(parse_intent(json.dumps(plan))) == text

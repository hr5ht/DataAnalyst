import json

import pytest

from app.agent.graph import GRAPH, describe, operation_steps, run_analysis, summarize_profile
from app.agent.intent import parse_intent
from app.agent.state import AnalysisContext
from app.analysis.profiler import DatasetProfile, profile_dataset
from app.retrieval.glossary import Definition, GlossaryError
from tests.fakes import TIMEOUT, ScriptedModel

SUM_BY_COUNTRY = {"tool": "aggregate_data", "operation": "sum", "column": "amount", "group_by": ["country"]}


def visited(question, df, model, search=None):
    context = AnalysisContext(df=df, model=model, search_glossary=search)
    return [node for step in GRAPH.stream({"question": question, "warnings": []}, context=context) for node in step]


def test_supported_question_runs_end_to_end(orders):
    model = ScriptedModel(SUM_BY_COUNTRY, "The UK spent the most, 110.5 in total.")
    state = run_analysis("Which country spent the most?", orders, model)
    assert state["status"] == "answered"
    assert state["message"] == "The UK spent the most, 110.5 in total."
    assert state["result"].rows == [["UK", 110.5], ["France", 20.0], ["Germany", 7.25]]
    assert "Excluded 1 row with a missing country value." in state["warnings"]
    assert len(model.calls) == 2
    explain_prompt = model.calls[1][1].content
    assert "Step that ran: Sum of amount by country" in explain_prompt
    assert '["UK", 110.5]' in explain_prompt

    model = ScriptedModel(SUM_BY_COUNTRY, "The UK spent the most.")
    assert visited("Which country spent the most?", orders, model) == [
        "validate",
        "retrieve",
        "understand",
        "execute",
        "check",
        "explain",
        "format",
    ]


def test_explanation_with_invented_numbers_is_replaced(orders):
    model = ScriptedModel(SUM_BY_COUNTRY, "The UK spent 120 in total, 6 times more than France.")
    state = run_analysis("Which country spent the most?", orders, model)
    assert state["status"] == "answered"
    assert state["message"] == "Sum of amount by country."
    assert any("numbers that are not in the result: 120, 6" in w for w in state["warnings"])


def test_explanation_failure_still_returns_the_result(orders):
    state = run_analysis("Which country spent the most?", orders, ScriptedModel(SUM_BY_COUNTRY, TIMEOUT))
    assert state["status"] == "answered"
    assert state["message"] == "Sum of amount by country."
    assert state["result"].rows[0] == ["UK", 110.5]
    assert any("took too long" in w for w in state["warnings"])


def test_profile_answer_is_written_without_the_model(orders):
    model = ScriptedModel({"tool": "profile_dataset"})
    state = run_analysis("Give me an overview", orders, model)
    assert state["status"] == "answered"
    assert isinstance(state["result"], DatasetProfile)
    assert state["message"].startswith("The dataset has 6 rows and 6 columns and no duplicate rows.")
    assert len(model.calls) == 1


def test_profile_summary_counts_duplicates_and_missing(load):
    profile = profile_dataset(load("a,b\n1,\n1,\n2,x\n"))
    assert summarize_profile(profile) == (
        "The dataset has 3 rows and 2 columns, with 1 duplicate row. Missing values appear in b."
    )


@pytest.mark.parametrize(
    ("plan", "status", "message"),
    [
        ({"tool": "clarify", "question": "Amount or quantity?"}, "clarify", "Amount or quantity?"),
        ({"tool": "unsupported", "reason": "Forecasts are not available."}, "unsupported", "Forecasts are not available."),
    ],
)
def test_clarify_and_unsupported_skip_execution(orders, plan, status, message):
    state = run_analysis("Which country is best?", orders, ScriptedModel(plan))
    assert (state["status"], state["message"]) == (status, message)
    assert "result" not in state
    assert visited("Which country is best?", orders, ScriptedModel(plan)) == [
        "validate",
        "retrieve",
        "understand",
        "format",
    ]


def test_blank_question_stops_before_the_model(orders):
    model = ScriptedModel()
    state = run_analysis("   ", orders, model)
    assert (state["status"], state["message"]) == ("error", "Ask a question about the dataset.")
    assert model.calls == []
    assert visited("   ", orders, ScriptedModel()) == ["validate", "format"]


def test_empty_dataset_is_rejected(orders):
    state = run_analysis("How many rows?", orders.iloc[0:0], ScriptedModel())
    assert state["status"] == "error"
    assert "no rows" in state["message"]


def test_empty_result_is_reported_without_explaining(orders):
    plan = {"tool": "filter_data", "conditions": [{"column": "country", "operator": "eq", "value": "Spain"}]}
    model = ScriptedModel(plan)
    state = run_analysis("Show orders from Spain", orders, model)
    assert state["status"] == "empty"
    assert "No rows matched the filters." in state["warnings"]
    assert len(model.calls) == 1


def test_malformed_plan_is_repaired_once(orders):
    model = ScriptedModel("not json", SUM_BY_COUNTRY, "The UK spent the most.")
    state = run_analysis("Which country spent the most?", orders, model)
    assert state["status"] == "answered"
    assert state["attempts"] == 2
    assert "Your previous plan was rejected: The model did not return valid JSON." in model.calls[1][1].content


def test_failed_tool_call_is_replanned_once(orders):
    bad = {"tool": "aggregate_data", "operation": "sum", "column": "country"}
    model = ScriptedModel(bad, SUM_BY_COUNTRY, "The UK spent the most.")
    state = run_analysis("Which country spent the most?", orders, model)
    assert state["status"] == "answered"
    assert "aggregate_data failed: Column country is not numeric." in model.calls[1][1].content


@pytest.mark.parametrize(
    ("first", "second", "message"),
    [
        ("not json", {**SUM_BY_COUNTRY, "column": "profit"}, "not in the dataset: profit"),
        (
            {"tool": "aggregate_data", "operation": "sum", "column": "country"},
            {"tool": "aggregate_data", "operation": "mean", "column": "country"},
            "Column country is not numeric",
        ),
    ],
)
def test_repairs_stop_after_two_attempts(orders, first, second, message):
    model = ScriptedModel(first, second, SUM_BY_COUNTRY)
    state = run_analysis("Total?", orders, model)
    assert state["status"] == "error"
    assert message in state["message"]
    assert len(model.calls) == 2
    assert "result" not in state


def test_provider_failure_is_not_retried(orders):
    model = ScriptedModel(TIMEOUT, SUM_BY_COUNTRY)
    state = run_analysis("Total amount?", orders, model)
    assert state["status"] == "error"
    assert state["provider_error"] is True
    assert state["message"] == "The LLM took too long to respond. Try again."
    assert len(model.calls) == 1


def test_definitions_are_retrieved_and_passed_to_the_planner(orders):
    definition = Definition(
        term="amount", kind="column", text="Order value in GBP.", glossary="Shop", source="shop.json", score=0.8
    )
    asked = []

    def search(question, columns):
        asked.append((question, columns))
        return [definition]

    model = ScriptedModel(SUM_BY_COUNTRY, "The UK spent the most.")
    state = run_analysis("Which country spent the most?", orders, model, search)
    assert asked == [("Which country spent the most?", list(orders.columns))]
    assert state["definitions"] == [definition]
    assert '"term": "amount", "kind": "column", "definition": "Order value in GBP."' in model.calls[0][1].content


def test_glossary_failure_is_a_warning_not_an_error(orders):
    def search(question, columns):
        raise GlossaryError("GEMINI_API_KEY is not set")

    state = run_analysis("Which country spent the most?", orders, ScriptedModel(SUM_BY_COUNTRY, "UK."), search)
    assert state["status"] == "answered"
    assert state["definitions"] == []
    assert "Glossary definitions were not used: GEMINI_API_KEY is not set" in state["warnings"]


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


@pytest.mark.parametrize(
    ("plan", "steps"),
    [
        (
            {
                "tool": "aggregate_data",
                "operation": "sum",
                "column": "Revenue",
                "group_by": ["Country"],
                "filters": [{"column": "Quantity", "operator": "gt", "value": 0}],
            },
            ["filter rows where Quantity > 0", "group by Country", "sum(Revenue)", "sort descending"],
        ),
        ({"tool": "aggregate_data", "operation": "count"}, ["count rows"]),
        (
            {"tool": "get_top_n", "group_by": "CustomerID", "column": "Revenue", "n": 5, "sort": "asc"},
            ["group by CustomerID", "sum(Revenue)", "keep the bottom 5"],
        ),
        (
            {
                "tool": "filter_data",
                "conditions": [
                    {"column": "Country", "operator": "in", "value": ["UK", "France"]},
                    {"column": "CustomerID", "operator": "is_null"},
                ],
                "columns": ["InvoiceNo"],
                "limit": 10,
            },
            ["keep rows where Country is one of UK, France", "keep rows where CustomerID is missing", "show InvoiceNo, up to 10 rows"],
        ),
        ({"tool": "compute_correlation", "columns": ["a", "b"], "method": "spearman"}, ["spearman correlation of a, b"]),
        (
            {"tool": "analyze_time_trend", "date_column": "d", "column": "v", "interval": "week", "start": "2011-01-01"},
            ["keep d from 2011-01-01 to the end", "group d by week", "sum(v)"],
        ),
        ({"tool": "profile_dataset"}, ["profile every column"]),
        ({"tool": "list_columns"}, ["list columns and types"]),
    ],
)
def test_operation_steps_read_like_the_work_done(plan, steps):
    assert operation_steps(parse_intent(json.dumps(plan))) == steps

import json

import pytest

from app.agent.intent import (
    AggregateIntent,
    ClarifyIntent,
    CorrelationIntent,
    FilterIntent,
    IntentError,
    ListColumnsIntent,
    ProfileIntent,
    TopNIntent,
    TrendIntent,
    UnsupportedIntent,
    check_columns,
    parse_intent,
    referenced_columns,
)


def parse(data):
    return parse_intent(json.dumps(data))


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"tool": "profile_dataset"}, ProfileIntent),
        ({"tool": "list_columns"}, ListColumnsIntent),
        ({"tool": "aggregate_data", "operation": "sum", "column": "Revenue", "group_by": ["Country"]}, AggregateIntent),
        ({"tool": "get_top_n", "group_by": "CustomerID", "column": "Revenue", "n": 10}, TopNIntent),
        (
            {"tool": "filter_data", "conditions": [{"column": "Country", "operator": "eq", "value": "France"}]},
            FilterIntent,
        ),
        ({"tool": "compute_correlation", "columns": ["Quantity", "UnitPrice"]}, CorrelationIntent),
        ({"tool": "analyze_time_trend", "date_column": "InvoiceDate", "column": "Revenue"}, TrendIntent),
        ({"tool": "clarify", "question": "Total revenue or number of orders?"}, ClarifyIntent),
        ({"tool": "unsupported", "reason": "Forecasting is not available."}, UnsupportedIntent),
    ],
)
def test_each_tool_parses_to_its_intent(data, expected):
    assert type(parse(data)) is expected


def test_arguments_and_defaults_are_kept():
    intent = parse(
        {"tool": "analyze_time_trend", "date_column": "InvoiceDate", "column": "Revenue", "start": "2011-01-01"}
    )
    assert intent.interval == "month"
    assert intent.operation == "sum"
    assert intent.start.isoformat() == "2011-01-01"
    assert intent.filters == []


def test_code_fences_are_ignored():
    text = '```json\n{"tool": "list_columns"}\n```'
    assert type(parse_intent(text)) is ListColumnsIntent


def test_referenced_columns_cover_every_field():
    intent = parse(
        {
            "tool": "aggregate_data",
            "operation": "sum",
            "column": "Revenue",
            "group_by": ["Country", "Revenue"],
            "filters": [{"column": "InvoiceDate", "operator": "gte", "value": "2011-01-01"}],
        }
    )
    assert referenced_columns(intent) == ["Revenue", "Country", "InvoiceDate"]
    top = parse({"tool": "get_top_n", "group_by": "CustomerID", "column": "Revenue"})
    assert referenced_columns(top) == ["Revenue", "CustomerID"]
    assert referenced_columns(parse({"tool": "profile_dataset"})) == []


def test_known_columns_pass_the_check():
    intent = parse({"tool": "compute_correlation", "columns": ["Quantity", "UnitPrice"]})
    check_columns(intent, ["Quantity", "UnitPrice", "Country"])


def test_unknown_columns_are_rejected_before_dispatch():
    intent = parse({"tool": "aggregate_data", "operation": "sum", "column": "Sales", "group_by": ["Region"]})
    with pytest.raises(IntentError, match="not in the dataset: Sales, Region"):
        check_columns(intent, ["Revenue", "Country"])


@pytest.mark.parametrize("text", ["", "not json", "{'tool': 'list_columns'}", '{"tool": "list_columns"'])
def test_output_that_is_not_json_is_rejected(text):
    with pytest.raises(IntentError, match="valid JSON"):
        parse_intent(text)


@pytest.mark.parametrize(
    "data",
    [
        [],
        "list_columns",
        {},
        {"tool": "run_python", "code": "import os; os.remove('data.csv')"},
        {"tool": "eval", "expression": "df.sum()"},
        {"tool": "LIST_COLUMNS"},
    ],
)
def test_unknown_or_missing_tools_are_rejected(data):
    with pytest.raises(IntentError, match="invalid plan"):
        parse(data)


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"tool": "aggregate_data", "operation": "variance", "column": "Revenue"}, "operation"),
        ({"tool": "aggregate_data", "operation": "sum", "column": "Revenue", "groupby": ["Country"]}, "groupby"),
        ({"tool": "aggregate_data", "operation": "sum", "group_by": ["a", "b", "c", "d"]}, "group_by"),
        ({"tool": "aggregate_data", "operation": "sum", "sort": "random"}, "sort"),
        ({"tool": "get_top_n", "group_by": "Country", "n": 1000}, "n"),
        ({"tool": "get_top_n", "group_by": "Country", "sort": None}, "sort"),
        ({"tool": "filter_data", "conditions": []}, "conditions"),
        ({"tool": "filter_data", "conditions": [{"column": "a", "operator": "like", "value": "x"}]}, "operator"),
        ({"tool": "filter_data", "conditions": [{"column": "a", "operator": "eq", "value": 1, "note": "x"}]}, "note"),
        ({"tool": "compute_correlation", "columns": ["Quantity"]}, "columns"),
        ({"tool": "compute_correlation", "columns": ["a", "b"], "method": "kendall"}, "method"),
        ({"tool": "analyze_time_trend", "date_column": "d", "interval": "hourly"}, "interval"),
        ({"tool": "analyze_time_trend", "date_column": "d", "start": "next week"}, "start"),
        ({"tool": "clarify", "question": ""}, "question"),
        ({"tool": "unsupported", "reason": "x" * 301}, "reason"),
        ({"tool": "list_columns", "columns": ["a"]}, "columns"),
    ],
)
def test_invalid_arguments_are_rejected_with_the_field_name(data, field):
    with pytest.raises(IntentError, match="invalid plan") as raised:
        parse(data)
    assert field in str(raised.value)


def test_validation_message_stays_short():
    data = {"tool": "aggregate_data", "operation": "x", "column": 1, "group_by": "y", "sort": "z", "filters": "w"}
    with pytest.raises(IntentError) as raised:
        parse(data)
    assert str(raised.value).count(";") <= 2


def test_unsupported_and_clarify_reference_no_columns():
    assert referenced_columns(parse({"tool": "unsupported", "reason": "Forecasts are not available."})) == []
    assert referenced_columns(parse({"tool": "clarify", "question": "Which metric?"})) == []


def test_arguments_nested_under_an_arguments_key_are_accepted():
    intent = parse({"tool": "compute_correlation", "arguments": {"columns": ["Quantity", "UnitPrice"]}})
    assert type(intent) is CorrelationIntent
    assert intent.columns == ["Quantity", "UnitPrice"]
    assert type(parse({"tool": "profile_dataset", "arguments": {}})) is ProfileIntent


def test_nested_arguments_are_still_validated():
    with pytest.raises(IntentError, match="code: Extra inputs"):
        parse({"tool": "list_columns", "arguments": {"code": "rm -rf /"}})
    with pytest.raises(IntentError, match="invalid plan"):
        parse({"tool": "get_top_n", "arguments": {"group_by": "Country"}, "n": 5})

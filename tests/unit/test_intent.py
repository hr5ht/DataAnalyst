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

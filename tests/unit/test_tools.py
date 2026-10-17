import io

import pandas as pd
import pytest
from pydantic import ValidationError

from app.analysis.tools import (
    MAX_RESULT_ROWS,
    AggregateArgs,
    AnalysisError,
    TopNArgs,
    aggregate_data,
    get_top_n,
    list_columns,
)

SALES = """region,product,sales,qty,returned
North,A,10,1,False
North,B,20,2,False
South,A,5,,True
South,A,,3,False
,B,7,1,False
East,C,100,10,True
"""


@pytest.fixture
def df():
    return pd.read_csv(io.StringIO(SALES))


def aggregate(df, **kwargs):
    return aggregate_data(df, AggregateArgs(**kwargs))


def test_list_columns(df):
    result = list_columns(df)
    assert result.columns == ["column", "type"]
    assert result.rows == [
        ["region", "text"],
        ["product", "text"],
        ["sales", "numeric"],
        ["qty", "numeric"],
        ["returned", "boolean"],
    ]


def test_sum_by_group_sorted_descending(df):
    result = aggregate(df, operation="sum", column="sales", group_by=["region"])
    assert result.columns == ["region", "sum_sales"]
    assert result.rows == [["East", 100], ["North", 30], ["South", 5]]
    assert result.warnings == [
        "Excluded 1 row with a missing region value.",
        "Ignored 1 row with a missing sales value.",
    ]


def test_mean_by_group(df):
    result = aggregate(df, operation="mean", column="qty", group_by=["region"])
    assert result.rows == [["East", 10], ["South", 3], ["North", 1.5]]


def test_count_rows_by_group_keeps_key_order_on_ties(df):
    result = aggregate(df, operation="count", group_by=["region"])
    assert result.columns == ["region", "count"]
    assert result.rows == [["North", 2], ["South", 2], ["East", 1]]


def test_count_with_column_counts_non_null_values(df):
    result = aggregate(df, operation="count", column="sales", group_by=["region"])
    assert result.rows == [["North", 2], ["East", 1], ["South", 1]]


def test_ascending_and_unsorted(df):
    ascending = aggregate(df, operation="max", column="sales", group_by=["region"], sort="asc")
    assert ascending.rows == [["South", 5], ["North", 20], ["East", 100]]
    unsorted = aggregate(df, operation="min", column="sales", group_by=["region"], sort=None)
    assert unsorted.rows == [["East", 100], ["North", 10], ["South", 5]]


def test_two_group_columns(df):
    result = aggregate(df, operation="sum", column="sales", group_by=["region", "product"])
    assert result.columns == ["region", "product", "sum_sales"]
    assert result.rows == [["East", "C", 100], ["North", "B", 20], ["North", "A", 10], ["South", "A", 5]]


def test_ungrouped_aggregations(df):
    assert aggregate(df, operation="sum", column="sales").rows == [[142]]
    assert aggregate(df, operation="median", column="qty").rows == [[2]]
    assert aggregate(df, operation="count").rows == [[6]]


def test_result_rows_are_capped():
    many = pd.DataFrame({"key": range(MAX_RESULT_ROWS + 100), "value": 1})
    result = aggregate(many, operation="sum", column="value", group_by=["key"])
    assert len(result.rows) == MAX_RESULT_ROWS
    assert result.warnings == [f"Showing the first {MAX_RESULT_ROWS} of {MAX_RESULT_ROWS + 100} groups."]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"operation": "sum", "column": "profit"}, "Unknown column: profit"),
        ({"operation": "sum", "column": "sales", "group_by": ["city"]}, "Unknown column: city"),
        ({"operation": "count", "column": "nope"}, "Unknown column: nope"),
        ({"operation": "sum", "column": "region"}, "not numeric"),
        ({"operation": "mean", "column": "returned"}, "not numeric"),
        ({"operation": "mean"}, "needs a numeric column"),
        ({"operation": "sum", "column": "sales", "group_by": ["region", "region"]}, "more than once"),
    ],
)
def test_invalid_arguments_raise_analysis_error(df, kwargs, message):
    with pytest.raises(AnalysisError, match=message):
        aggregate(df, **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"operation": "variance", "column": "sales"},
        {"operation": "sum", "column": "sales", "group_by": ["a", "b", "c", "d"]},
        {"operation": "sum", "column": "sales", "sort": "random"},
    ],
)
def test_unsupported_arguments_fail_validation(kwargs):
    with pytest.raises(ValidationError):
        AggregateArgs(**kwargs)


def test_top_n(df):
    result = get_top_n(df, TopNArgs(group_by="region", column="sales", n=2))
    assert result.rows == [["East", 100], ["North", 30]]
    assert len(result.warnings) == 2


def test_bottom_n(df):
    result = get_top_n(df, TopNArgs(group_by="region", column="sales", n=1, sort="asc"))
    assert result.rows == [["South", 5]]


def test_top_n_by_count(df):
    result = get_top_n(df, TopNArgs(group_by="product", operation="count", n=2))
    assert result.rows == [["A", 3], ["B", 2]]
    assert result.warnings == []


@pytest.mark.parametrize("n", [0, 101])
def test_top_n_bounds(n):
    with pytest.raises(ValidationError):
        TopNArgs(group_by="region", column="sales", n=n)


def test_top_n_rejects_text_metric(df):
    with pytest.raises(AnalysisError, match="not numeric"):
        get_top_n(df, TopNArgs(group_by="region", column="product"))

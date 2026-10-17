import pytest
from pydantic import ValidationError

from app.analysis.tools import AggregateArgs, AnalysisError, Condition, FilterArgs, aggregate_data, filter_data


def ids(df, *conditions, **kwargs):
    args = FilterArgs(conditions=[Condition(**c) for c in conditions], columns=["order_id"], **kwargs)
    return [row[0] for row in filter_data(df, args).rows]


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"column": "country", "operator": "eq", "value": "UK"}, [1, 3, 5]),
        ({"column": "country", "operator": "ne", "value": "UK"}, [2, 4]),
        ({"column": "amount", "operator": "gt", "value": 10}, [1, 2, 5]),
        ({"column": "amount", "operator": "lte", "value": 7.25}, [4, 6]),
        ({"column": "ordered_at", "operator": "gte", "value": "2011-02-01"}, [3, 4, 5]),
        ({"column": "ordered_at", "operator": "lt", "value": "2011-01-15"}, [1]),
        ({"column": "country", "operator": "in", "value": ["France", "Germany"]}, [2, 4]),
        ({"column": "qty", "operator": "in", "value": [2, 3]}, [2, 3]),
        ({"column": "country", "operator": "contains", "value": "fr"}, [2]),
        ({"column": "country", "operator": "contains", "value": "."}, []),
        ({"column": "paid", "operator": "eq", "value": True}, [1, 3, 4, 6]),
        ({"column": "amount", "operator": "is_null"}, [3]),
        ({"column": "ordered_at", "operator": "not_null"}, [1, 2, 3, 4, 5]),
    ],
)
def test_single_condition(orders, condition, expected):
    assert ids(orders, condition) == expected


def test_conditions_are_combined_with_and(orders):
    conditions = [
        {"column": "country", "operator": "eq", "value": "UK"},
        {"column": "amount", "operator": "gt", "value": 50},
    ]
    assert ids(orders, *conditions) == [5]


def test_limit_and_warning(orders):
    args = FilterArgs(conditions=[Condition(column="order_id", operator="not_null")], limit=2)
    result = filter_data(orders, args)
    assert len(result.rows) == 2
    assert result.columns[0] == "order_id"
    assert result.rows[0][-1] == "2011-01-03T00:00:00.000"
    assert result.warnings == ["Showing the first 2 of 6 matching rows."]


def test_no_matches(orders):
    args = FilterArgs(conditions=[Condition(column="country", operator="eq", value="Spain")])
    result = filter_data(orders, args)
    assert result.rows == []
    assert result.warnings == ["No rows matched the filters."]


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ({"column": "city", "operator": "eq", "value": "x"}, "Unknown column: city"),
        ({"column": "country", "operator": "gt", "value": "UK"}, "can only be filtered with"),
        ({"column": "amount", "operator": "eq", "value": "10"}, "must be numbers"),
        ({"column": "amount", "operator": "eq", "value": True}, "must be numbers"),
        ({"column": "country", "operator": "eq", "value": 5}, "must be text"),
        ({"column": "paid", "operator": "eq", "value": 1}, "true or false"),
        ({"column": "ordered_at", "operator": "gt", "value": "03/01/2011"}, "YYYY-MM-DD"),
        ({"column": "ordered_at", "operator": "gt", "value": "2011-13-45"}, "not a valid date"),
        ({"column": "amount", "operator": "contains", "value": "1"}, "only works on text"),
        ({"column": "country", "operator": "in", "value": "UK"}, "non-empty list"),
        ({"column": "country", "operator": "in", "value": []}, "non-empty list"),
        ({"column": "country", "operator": "eq", "value": ["UK"]}, "single value"),
        ({"column": "country", "operator": "eq"}, "needs a value"),
    ],
)
def test_invalid_conditions(orders, condition, message):
    with pytest.raises(AnalysisError, match=message):
        ids(orders, condition)


def test_unknown_operator_and_empty_conditions_fail_validation():
    with pytest.raises(ValidationError):
        Condition(column="amount", operator="like", value="x")
    with pytest.raises(ValidationError):
        FilterArgs(conditions=[])


def test_filters_apply_before_aggregation(orders):
    args = AggregateArgs(
        operation="sum",
        column="amount",
        group_by=["country"],
        filters=[Condition(column="paid", operator="eq", value=True)],
    )
    result = aggregate_data(orders, args)
    assert result.rows == [["UK", 10.5], ["Germany", 7.25]]
    assert result.warnings == [
        "Excluded 1 row with a missing country value.",
        "Ignored 1 row with a missing amount value.",
    ]

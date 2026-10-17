import pytest

from app.analysis.tools import AnalysisError, Condition, TrendArgs, analyze_time_trend


def trend(df, **kwargs):
    return analyze_time_trend(df, TrendArgs(date_column="ordered_at", **kwargs))


def test_monthly_sum(orders):
    result = trend(orders, column="amount")
    assert result.columns == ["period", "sum_amount"]
    assert result.rows == [["2011-01", 30.5], ["2011-02", 7.25], ["2011-03", 100]]
    assert result.warnings == [
        "Excluded 1 row with a missing ordered_at value.",
        "Ignored 1 row with a missing amount value.",
    ]


def test_monthly_count(orders):
    assert trend(orders, operation="count").rows == [["2011-01", 2], ["2011-02", 2], ["2011-03", 1]]


@pytest.mark.parametrize(
    ("interval", "labels"),
    [
        ("day", ["2011-01-03", "2011-01-15", "2011-02-01", "2011-02-20", "2011-03-05"]),
        ("week", ["2011-01-03", "2011-01-10", "2011-01-31", "2011-02-14", "2011-02-28"]),
        ("quarter", ["2011Q1"]),
        ("year", ["2011"]),
    ],
)
def test_interval_labels(orders, interval, labels):
    assert [row[0] for row in trend(orders, operation="count", interval=interval).rows] == labels


def test_date_range_is_inclusive(orders):
    result = trend(orders, operation="count", start="2011-01-15", end="2011-02-01")
    assert result.rows == [["2011-01", 1], ["2011-02", 1]]


def test_end_date_includes_times_on_that_day(load):
    df = load("at,v\n2011-02-01 15:30:00,1\n2011-02-02 00:00:00,2\n")
    result = analyze_time_trend(df, TrendArgs(date_column="at", column="v", interval="day", end="2011-02-01"))
    assert result.rows == [["2011-02-01", 1]]


def test_group_with_only_missing_values_has_no_sum(orders):
    result = trend(orders, column="amount", filters=[Condition(column="country", operator="eq", value="UK")])
    assert result.rows == [["2011-01", 10.5], ["2011-02", None], ["2011-03", 100]]


def test_empty_range(orders):
    result = trend(orders, column="amount", start="2012-01-01")
    assert result.rows == []
    assert result.warnings[-1] == "No rows fall in the selected date range."


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"date_column": "country"}, "not a date column"),
        ({"date_column": "missing"}, "Unknown column"),
        ({"date_column": "ordered_at", "column": "country"}, "not numeric"),
        ({"date_column": "ordered_at", "operation": "mean"}, "needs a numeric column"),
        (
            {"date_column": "ordered_at", "operation": "count", "start": "2011-03-01", "end": "2011-01-01"},
            "start date is after",
        ),
    ],
)
def test_invalid_trend_arguments(orders, kwargs, message):
    with pytest.raises(AnalysisError, match=message):
        analyze_time_trend(orders, TrendArgs(**kwargs))


def test_non_iso_dates_are_not_treated_as_dates(load):
    df = load("day,v\n01/03/2011,1\n02/03/2011,2\n")
    with pytest.raises(AnalysisError, match="YYYY-MM-DD"):
        analyze_time_trend(df, TrendArgs(date_column="day", column="v"))

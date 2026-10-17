import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.analysis.tools import AnalysisError, Condition, CorrelationArgs, compute_correlation


def correlate(df, *columns, **kwargs):
    return compute_correlation(df, CorrelationArgs(columns=list(columns), **kwargs))


def test_pearson_uses_rows_with_both_values(orders):
    result = correlate(orders, "amount", "qty")
    assert result.columns == ["column_a", "column_b", "correlation", "rows_used"]
    a, b, value, used = result.rows[0]
    expected = np.corrcoef([10.5, 20, 7.25, 100, 3], [1, 2, 1, 10, 1])[0, 1]
    assert (a, b, used) == ("amount", "qty", 5)
    assert value == pytest.approx(expected)


def test_spearman_is_rank_based():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [5, 6, 7, 8, 70]})
    assert correlate(df, "x", "y", method="spearman").rows[0][2] == pytest.approx(1.0)
    assert correlate(df, "x", "y").rows[0][2] < 0.9


def test_every_pair_is_reported(orders):
    result = correlate(orders, "amount", "qty", "order_id")
    assert [row[:2] for row in result.rows] == [["amount", "qty"], ["amount", "order_id"], ["qty", "order_id"]]


def test_constant_column_has_no_correlation():
    df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 4, 4]})
    result = correlate(df, "x", "y")
    assert result.rows[0][2] is None
    assert "no variation" in result.warnings[0]


def test_too_few_rows(orders):
    result = correlate(orders, "amount", "qty", filters=[Condition(column="country", operator="eq", value="UK")])
    assert result.rows[0][2:] == [None, 2]
    assert "Not enough rows" in result.warnings[0]


@pytest.mark.parametrize(
    ("columns", "message"),
    [
        (["amount", "country"], "not numeric"),
        (["amount", "paid"], "not numeric"),
        (["amount", "nope"], "Unknown column"),
        (["amount", "amount"], "more than once"),
    ],
)
def test_invalid_columns(orders, columns, message):
    with pytest.raises(AnalysisError, match=message):
        correlate(orders, *columns)


def test_needs_two_columns():
    with pytest.raises(ValidationError):
        CorrelationArgs(columns=["amount"])

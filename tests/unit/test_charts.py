import pytest
from pydantic import ValidationError

from app.analysis.charts import MAX_BARS, ChartSpec, chart_for
from app.analysis.tools import TableResult


def table(columns, rows):
    return TableResult(columns=columns, rows=rows)


def test_trend_becomes_a_line_chart():
    spec = chart_for("analyze_time_trend", "Sum of Revenue per month", table(["period", "sum_Revenue"], [["2011-01", 5], ["2011-02", None]]))
    assert (spec.type, spec.x, spec.y) == ("line", ["2011-01", "2011-02"], [5, None])
    assert (spec.x_label, spec.y_label) == ("period", "sum_Revenue")


def test_groups_become_bars_and_multiple_keys_are_joined():
    spec = chart_for("aggregate_data", "Sum", table(["Country", "Year", "sum_Revenue"], [["UK", 2011, 10.5]]))
    assert (spec.type, spec.x, spec.y, spec.x_label) == ("bar", ["UK / 2011"], [10.5], "Country / Year")


def test_long_bar_charts_are_cut_and_say_so():
    rows = [[f"c{i}", i] for i in range(MAX_BARS + 5)]
    spec = chart_for("get_top_n", "Top customers", table(["CustomerID", "sum_Revenue"], rows))
    assert len(spec.x) == MAX_BARS
    assert spec.title == f"Top customers (first {MAX_BARS})"


def test_correlation_pairs_become_bars():
    rows = [["Quantity", "UnitPrice", -0.5, 10], ["Quantity", "Revenue", 0.9, 10]]
    spec = chart_for("compute_correlation", "Pearson", table(["column_a", "column_b", "correlation", "rows_used"], rows))
    assert spec.x == ["Quantity × UnitPrice", "Quantity × Revenue"]
    assert spec.y == [-0.5, 0.9]


@pytest.mark.parametrize(
    ("tool", "columns", "rows"),
    [
        ("filter_data", ["a", "b"], [[1, 2]]),
        ("profile_dataset", ["column", "type"], [["a", "numeric"]]),
        ("aggregate_data", ["sum_Revenue"], [[10]]),
        ("aggregate_data", ["Country", "sum_Revenue"], []),
        ("aggregate_data", ["Country", "sum_Revenue"], [["UK", None]]),
        ("aggregate_data", ["Country", "Region"], [["UK", "North"]]),
        ("aggregate_data", ["Country", "flag"], [["UK", True]]),
    ],
)
def test_results_without_plottable_numbers_have_no_chart(tool, columns, rows):
    assert chart_for(tool, "t", table(columns, rows)) is None


@pytest.mark.parametrize(
    "data",
    [
        {"type": "pie", "title": "t", "x_label": "x", "y_label": "y", "x": ["a"], "y": [1]},
        {"type": "bar", "title": "t", "x_label": "x", "y_label": "y", "x": ["a", "b"], "y": [1]},
        {"type": "bar", "title": "t", "x_label": "x", "y_label": "y", "x": [], "y": []},
        {"type": "bar", "title": "t", "x_label": "x", "y_label": "y", "x": ["a"], "y": [1], "script": "alert(1)"},
    ],
)
def test_chart_spec_rejects_unknown_or_malformed_charts(data):
    with pytest.raises(ValidationError):
        ChartSpec(**data)

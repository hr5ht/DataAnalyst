from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.analysis.tools import (
    AggregateArgs,
    Condition,
    CorrelationArgs,
    FilterArgs,
    TopNArgs,
    TrendArgs,
    aggregate_data,
    analyze_time_trend,
    compute_correlation,
    filter_data,
    get_top_n,
    list_columns,
)
from app.storage import get_store
from app.main import app

SALES = Path(__file__).parent.parent / "data" / "sales.csv"


@pytest.fixture(scope="module")
def uploaded():
    client = TestClient(app)
    response = client.post("/datasets", files={"file": ("sales.csv", SALES.read_bytes(), "text/csv")})
    assert response.status_code == 201
    body = response.json()
    return body["profile"], get_store().get(body["dataset_id"])


@pytest.fixture(scope="module")
def sales(uploaded):
    return uploaded[1]


def test_profile_reports_missing_values_and_duplicates(uploaded):
    profile = uploaded[0]
    assert profile["rows"] == 14
    assert profile["duplicate_rows"] == 1
    missing = {c["name"]: c["missing"] for c in profile["column_profiles"] if c["missing"]}
    assert missing == {"Description": 1, "CustomerID": 2}


def test_column_types(sales):
    assert dict(list_columns(sales).rows) == {
        "InvoiceNo": "text",
        "StockCode": "text",
        "Description": "text",
        "Quantity": "numeric",
        "InvoiceDate": "datetime",
        "UnitPrice": "numeric",
        "CustomerID": "numeric",
        "Country": "text",
        "Revenue": "numeric",
    }


def test_revenue_by_country(sales):
    result = aggregate_data(sales, AggregateArgs(operation="sum", column="Revenue", group_by=["Country"]))
    assert result.rows == [["United Kingdom", 240], ["France", 46], ["Germany", 45], ["Netherlands", 45]]
    assert result.warnings == []


def test_monthly_revenue(sales):
    result = analyze_time_trend(sales, TrendArgs(date_column="InvoiceDate", column="Revenue"))
    assert result.rows == [["2010-12", 90], ["2011-01", 57], ["2011-02", 184], ["2011-03", 45]]


def test_top_customers_by_spend(sales):
    result = get_top_n(sales, TopNArgs(group_by="CustomerID", column="Revenue", n=3))
    assert result.rows == [[104, 150], [102, 46], [103, 45]]
    assert result.warnings == ["Excluded 2 rows with a missing CustomerID value."]


def test_quantity_and_price_correlation(sales):
    result = compute_correlation(sales, CorrelationArgs(columns=["Quantity", "UnitPrice"]))
    quantity = [10, 2, 5, 20, 1, 4, -3, 12, 10, 10, 1, 8, 3, 6]
    price = [2, 15, 2, 1.5, 15, 7.5, 2, 1.5, 7.5, 7.5, 18, 2, 15, 0]
    assert result.rows[0][2] == pytest.approx(np.corrcoef(quantity, price)[0, 1])
    assert result.rows[0][3] == 14


def test_orders_per_country(sales):
    result = aggregate_data(sales, AggregateArgs(operation="count", group_by=["Country"]))
    assert result.rows == [["United Kingdom", 7], ["France", 3], ["Germany", 3], ["Netherlands", 1]]


def test_filtered_rows(sales):
    args = FilterArgs(
        conditions=[
            Condition(column="Country", operator="eq", value="France"),
            Condition(column="Revenue", operator="gt", value=15),
        ],
        columns=["InvoiceNo", "Revenue"],
    )
    assert filter_data(sales, args).rows == [["1006", 18], ["1008", 18]]


def test_cancellations(sales):
    args = FilterArgs(
        conditions=[Condition(column="InvoiceNo", operator="contains", value="c")],
        columns=["InvoiceNo"],
    )
    assert filter_data(sales, args).rows == [["C1005"]]


def test_trend_with_date_range(sales):
    args = TrendArgs(date_column="InvoiceDate", operation="count", start="2011-01-01", end="2011-02-28")
    assert analyze_time_trend(sales, args).rows == [["2011-01", 4], ["2011-02", 4]]

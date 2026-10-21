from pathlib import Path

import groq
import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.questions import MAX_TABLE_ROWS, get_glossary_search, get_model
from app.config import Settings, get_settings
from app.main import app
from app.retrieval.glossary import Definition, GlossaryError
from app.storage import DatasetStore, get_store
from tests.fakes import REQUEST, TIMEOUT, ScriptedModel

SALES = (Path(__file__).parent.parent / "data" / "sales.csv").read_bytes()


@pytest.fixture
def client():
    store = DatasetStore(max_datasets=10, ttl_seconds=3600)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_glossary_search] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client, content=SALES, name="sales.csv"):
    response = client.post("/datasets", files={"file": (name, content, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def ask(client, dataset_id, question, *replies):
    model = ScriptedModel(*replies)
    app.dependency_overrides[get_model] = lambda: model
    return client.post(f"/datasets/{dataset_id}/questions", json={"question": question})


@pytest.mark.parametrize(
    ("question", "plan", "explanation", "rows", "chart"),
    [
        (
            "Which country made the most revenue?",
            {"tool": "get_top_n", "group_by": "Country", "column": "Revenue", "n": 1},
            "The United Kingdom made the most revenue, 240.",
            [["United Kingdom", 240]],
            "bar",
        ),
        (
            "Show the monthly revenue trend",
            {"tool": "analyze_time_trend", "date_column": "InvoiceDate", "column": "Revenue"},
            "Revenue peaked in 2011-02 at 184.",
            [["2010-12", 90], ["2011-01", 57], ["2011-02", 184], ["2011-03", 45]],
            "line",
        ),
        (
            "Which product brought in the most money?",
            {"tool": "get_top_n", "group_by": "Description", "column": "Revenue", "n": 2},
            "FRAME brought in the most, 180.",
            [["FRAME", 180], ["LAMP", 90]],
            "bar",
        ),
        (
            "How many lines does each country have?",
            {"tool": "aggregate_data", "operation": "count", "group_by": ["Country"]},
            "The United Kingdom has the most lines, 7.",
            [["United Kingdom", 7], ["France", 3], ["Germany", 3], ["Netherlands", 1]],
            "bar",
        ),
        (
            "Show cancelled lines",
            {"tool": "filter_data", "conditions": [{"column": "Quantity", "operator": "lt", "value": 0}], "columns": ["InvoiceNo", "Quantity"]},
            "One line was cancelled: C1005, with a quantity of -3.",
            [["C1005", -3]],
            None,
        ),
    ],
)
def test_supported_questions_return_grounded_answers(client, question, plan, explanation, rows, chart):
    response = ask(client, upload(client), question, plan, explanation)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["answer"] == explanation
    assert body["question"] == question
    assert body["operation"]["tool"] == plan["tool"]
    assert body["table"]["rows"] == rows
    assert body["table"]["total_rows"] == len(rows)
    assert (body["chart"] or {}).get("type") == chart
    assert len(body["request_id"]) == 32


def test_chart_matches_the_table(client):
    plan = {"tool": "analyze_time_trend", "date_column": "InvoiceDate", "column": "Revenue"}
    body = ask(client, upload(client), "Monthly revenue?", plan, "Revenue peaked at 184.").json()
    assert body["chart"]["x"] == [row[0] for row in body["table"]["rows"]]
    assert body["chart"]["y"] == [row[1] for row in body["table"]["rows"]]
    assert body["chart"]["title"] == body["operation"]["description"] == "Sum of Revenue per month of InvoiceDate"


def test_operation_lists_the_arguments_used(client):
    plan = {"tool": "get_top_n", "group_by": "Country", "column": "Revenue", "n": 1}
    operation = ask(client, upload(client), "Top country?", plan, "United Kingdom.").json()["operation"]
    assert operation == {
        "tool": "get_top_n",
        "description": "Top 1 Country by sum of Revenue",
        "steps": ["group by Country", "sum(Revenue)", "keep the top 1"],
        "arguments": {"group_by": "Country", "operation": "sum", "column": "Revenue", "n": 1, "sort": "desc", "filters": []},
    }


def test_overview_returns_the_profile_as_a_table(client):
    body = ask(client, upload(client), "Give me an overview", {"tool": "profile_dataset"}).json()
    assert body["status"] == "answered"
    assert body["answer"].startswith("The dataset has 14 rows and 9 columns, with 1 duplicate row.")
    assert body["table"]["columns"] == ["column", "type", "missing", "unique"]
    assert ["CustomerID", "numeric", 2, 5] in body["table"]["rows"]
    assert body["chart"] is None


@pytest.mark.parametrize(
    ("plan", "status", "answer"),
    [
        ({"tool": "clarify", "question": "Revenue or units sold?"}, "clarify", "Revenue or units sold?"),
        ({"tool": "unsupported", "reason": "Forecasting is not supported."}, "unsupported", "Forecasting is not supported."),
    ],
)
def test_clarify_and_unsupported_have_no_table(client, plan, status, answer):
    body = ask(client, upload(client), "Which product is best?", plan).json()
    assert (body["status"], body["answer"]) == (status, answer)
    assert body["operation"] is None and body["table"] is None and body["chart"] is None


def test_empty_result_is_reported(client):
    plan = {"tool": "filter_data", "conditions": [{"column": "Country", "operator": "eq", "value": "Spain"}]}
    body = ask(client, upload(client), "Orders from Spain?", plan).json()
    assert body["status"] == "empty"
    assert body["table"]["rows"] == [] and body["chart"] is None
    assert "No rows matched the filters." in body["warnings"]


@pytest.mark.parametrize(
    ("replies", "message"),
    [
        (["not json", "still not json"], "The model did not return valid JSON."),
        (
            [{"tool": "aggregate_data", "operation": "sum", "column": "Profit"}] * 2,
            "The plan uses columns that are not in the dataset: Profit.",
        ),
        (
            [{"tool": "run_python", "code": "import os"}] * 2,
            "The model returned an invalid plan",
        ),
    ],
)
def test_invalid_model_output_ends_in_an_error_answer(client, replies, message):
    response = ask(client, upload(client), "Total profit?", *replies)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert message in body["answer"]


def provider_error(cls, code):
    return cls("provider said no", response=httpx.Response(code, request=REQUEST), body=None)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (TIMEOUT, "took too long"),
        (provider_error(groq.RateLimitError, 429), "rate limit"),
        (provider_error(groq.AuthenticationError, 401), "rejected the API key"),
    ],
)
def test_provider_failures_return_503(client, error, message):
    response = ask(client, upload(client), "Total revenue?", error)
    assert response.status_code == 503
    assert message in response.json()["detail"]


def test_missing_groq_key_returns_503(client):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    dataset_id = upload(client)
    app.dependency_overrides.pop(get_model, None)
    response = client.post(f"/datasets/{dataset_id}/questions", json={"question": "Total revenue?"})
    assert response.status_code == 503
    assert "GROQ_API_KEY is not set" in response.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"question": "   "}, "Ask a question about the dataset."),
        ({"question": "x" * 501}, "Keep the question under 500 characters."),
        ({}, "question: Field required"),
        ({"question": "Total?", "code": "import os"}, "code: Extra inputs are not permitted"),
    ],
)
def test_bad_requests_return_a_single_message(client, payload, detail):
    app.dependency_overrides[get_model] = lambda: ScriptedModel()
    response = client.post(f"/datasets/{upload(client)}/questions", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}


def test_unknown_dataset_returns_404(client):
    response = ask(client, "0" * 32, "Total revenue?")
    assert response.status_code == 404
    assert response.json() == {"detail": "Dataset not found."}


def test_questions_only_see_their_own_dataset(client):
    first = upload(client, b"city,sales\nParis,10\nRome,5\n", "a.csv")
    second = upload(client, b"city,sales\nOslo,99\n", "b.csv")
    plan = {"tool": "aggregate_data", "operation": "sum", "column": "sales", "group_by": ["city"]}
    assert ask(client, first, "Sales by city?", plan, "Paris leads with 10.").json()["table"]["rows"] == [
        ["Paris", 10],
        ["Rome", 5],
    ]
    assert ask(client, second, "Sales by city?", plan, "Oslo has 99.").json()["table"]["rows"] == [["Oslo", 99]]


def test_large_tables_are_cut_with_a_warning(client):
    content = "id\n" + "\n".join(str(i) for i in range(MAX_TABLE_ROWS + 50))
    plan = {"tool": "aggregate_data", "operation": "count", "group_by": ["id"], "sort": None}
    body = ask(client, upload(client, content.encode()), "Count per id", plan, "Each id appears once.").json()
    assert len(body["table"]["rows"]) == MAX_TABLE_ROWS
    assert body["table"]["total_rows"] == MAX_TABLE_ROWS + 50
    assert f"The table shows the first {MAX_TABLE_ROWS} of {MAX_TABLE_ROWS + 50} rows." in body["warnings"]


def test_long_text_cells_are_clipped(client):
    content = f"note,n\n{'x' * 500},1\n".encode()
    plan = {"tool": "filter_data", "conditions": [{"column": "n", "operator": "eq", "value": 1}]}
    body = ask(client, upload(client, content), "Show the note", plan, "Here is the note.").json()
    assert body["table"]["rows"][0][0] == "x" * 200 + "..."


def test_definitions_are_returned_with_their_source(client):
    definition = Definition(
        term="Revenue", kind="metric", text="Quantity times UnitPrice.", glossary="Retail", source="retail.json", score=0.7
    )
    app.dependency_overrides[get_glossary_search] = lambda: lambda question, columns: [definition]
    plan = {"tool": "aggregate_data", "operation": "sum", "column": "Revenue"}
    body = ask(client, upload(client), "Total revenue?", plan, "Total revenue is 404.").json()
    assert body["definitions"] == [definition.model_dump()]


def test_unavailable_glossary_is_a_warning(client):
    def search(question, columns):
        raise GlossaryError("GEMINI_API_KEY is not set")

    app.dependency_overrides[get_glossary_search] = lambda: search
    plan = {"tool": "aggregate_data", "operation": "sum", "column": "Revenue"}
    body = ask(client, upload(client), "Total revenue?", plan, "Total revenue is 404.").json()
    assert body["status"] == "answered"
    assert "Glossary definitions were not used: GEMINI_API_KEY is not set" in body["warnings"]

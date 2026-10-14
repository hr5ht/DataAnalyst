import pytest
from fastapi.testclient import TestClient

from app.api.datasets import DATASETS
from app.config import Settings, get_settings
from app.main import app

client = TestClient(app)


@pytest.fixture
def limits():
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, max_upload_mb=0.001, max_rows=3, max_columns=3
    )
    yield
    app.dependency_overrides.clear()


def upload(content: bytes | str, filename: str = "data.csv"):
    if isinstance(content, str):
        content = content.encode()
    return client.post("/datasets", files={"file": (filename, content, "text/csv")})


def test_valid_csv_returns_dataset_id():
    response = upload("category,sales\nFurniture,10.5\nOffice,3\n")
    assert response.status_code == 201
    body = response.json()
    assert body["rows"] == 2
    assert body["columns"] == ["category", "sales"]
    assert body["filename"] == "data.csv"
    assert DATASETS[body["dataset_id"]]["sales"].sum() == 13.5


def test_utf8_bom_is_stripped_from_header():
    response = upload("﻿city,count\nPune,1\n".encode("utf-8"))
    assert response.status_code == 201
    assert response.json()["columns"] == ["city", "count"]


def test_each_upload_gets_a_new_id():
    first = upload("a\n1\n").json()["dataset_id"]
    second = upload("a\n1\n").json()["dataset_id"]
    assert first != second


@pytest.mark.parametrize("filename", ["data.txt", "data.xlsx", "data", "data.csv.exe"])
def test_rejects_non_csv_extension(filename):
    assert upload("a,b\n1,2\n", filename=filename).status_code == 415


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "empty"),
        ("\n\n  \n", "empty"),
        ("a,b\n", "no data rows"),
        ("a,b\n1,2\n3,4,5\n", "Could not parse"),
        ('a,b\n"1,2\n', "Could not parse"),
        ("a,b\n1,2,3\n4,5,6\n", "more fields than the header"),
        ("name\ncafé\n".encode("latin-1"), "UTF-8"),
        ("a,b\n1,2\n".encode("utf-16"), "UTF-8"),
        (b"\x89PNG\r\n\x1a\n\x00\x00", "UTF-8"),
    ],
)
def test_rejects_malformed_csv(content, message):
    response = upload(content)
    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_missing_file_is_validation_error():
    assert client.post("/datasets").status_code == 422


def test_rejects_oversized_file(limits):
    response = upload("a\n" + "1\n" * 1000)
    assert response.status_code == 413
    assert "MB" in response.json()["detail"]


def test_rejects_too_many_rows(limits):
    response = upload("a\n1\n2\n3\n4\n")
    assert response.status_code == 413
    assert "rows" in response.json()["detail"]


def test_accepts_rows_at_limit(limits):
    assert upload("a\n1\n2\n3\n").status_code == 201


def test_rejects_too_many_columns(limits):
    response = upload("a,b,c,d\n1,2,3,4\n")
    assert response.status_code == 413
    assert "columns" in response.json()["detail"]


def test_short_rows_become_missing_values():
    response = upload("a,b\n1,2\n3\n")
    assert response.status_code == 201
    assert DATASETS[response.json()["dataset_id"]]["b"].isna().sum() == 1

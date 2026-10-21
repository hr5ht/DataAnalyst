from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.questions import get_glossary_search, get_model
from app.auth import COOKIE, Usage, get_usage
from app.config import Settings, get_settings
from app.main import app
from app.storage import DatasetStore, get_store
from tests.fakes import ScriptedModel

SALES = (Path(__file__).parent.parent / "data" / "sales.csv").read_bytes()
LOGIN = {"username": "recruiter", "password": "open sesame"}
PLAN = {"tool": "aggregate_data", "operation": "sum", "column": "Revenue"}


@pytest.fixture
def client():
    settings = Settings(
        _env_file=None,
        demo_username="recruiter",
        demo_password=SecretStr("open sesame"),
        demo_daily_questions=2,
        demo_daily_uploads=2,
    )
    store, usage = DatasetStore(10, 3600), Usage()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_usage] = lambda: usage
    app.dependency_overrides[get_glossary_search] = lambda: None
    app.dependency_overrides[get_model] = lambda: ScriptedModel(PLAN, "Total revenue is 404.")
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client):
    return client.post("/datasets", files={"file": ("sales.csv", SALES, "text/csv")})


def ask(client, dataset_id):
    app.dependency_overrides[get_model] = lambda: ScriptedModel(PLAN, "Total revenue is 404.")
    return client.post(f"/datasets/{dataset_id}/questions", json={"question": "Total revenue?"})


def test_data_routes_need_a_session(client):
    assert upload(client).status_code == 401
    assert client.get("/datasets/abc").json() == {"detail": "Sign in to use the demo."}
    assert client.post("/datasets/abc/questions", json={"question": "Total?"}).status_code == 401


def test_public_pages_stay_open(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/sample.csv").status_code == 200
    assert client.get("/auth/session").json() == {
        "auth_required": True,
        "authenticated": False,
        "username": None,
        "questions_left": None,
        "uploads_left": None,
    }


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": "recruiter", "password": "wrong"},
        {"username": "admin", "password": "open sesame"},
        {"username": "", "password": ""},
    ],
)
def test_wrong_credentials_are_rejected(client, credentials):
    response = client.post("/auth/login", json=credentials)
    assert response.status_code == 401
    assert response.json() == {"detail": "Wrong username or password."}
    assert COOKIE not in response.cookies


def test_login_sets_a_strict_http_only_cookie(client):
    response = client.post("/auth/login", json=LOGIN)
    assert response.status_code == 200
    assert response.json()["questions_left"] == 2
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "open sesame" not in response.headers["set-cookie"]


def test_signed_in_demo_flow_counts_down_and_stops_at_the_cap(client):
    client.post("/auth/login", json=LOGIN)
    dataset_id = upload(client).json()["dataset_id"]
    assert ask(client, dataset_id).status_code == 200
    assert client.get("/auth/session").json()["questions_left"] == 1
    assert ask(client, dataset_id).status_code == 200
    blocked = ask(client, dataset_id)
    assert blocked.status_code == 429
    assert "allows 2 questions a day" in blocked.json()["detail"]
    assert client.get("/auth/session").json()["questions_left"] == 0


def test_uploads_are_capped_too(client):
    client.post("/auth/login", json=LOGIN)
    assert [upload(client).status_code for _ in range(3)] == [201, 201, 429]


def test_failed_lookups_do_not_use_up_questions(client):
    client.post("/auth/login", json=LOGIN)
    assert ask(client, "0" * 32).status_code == 404
    assert client.get("/auth/session").json()["questions_left"] == 2


def test_logout_clears_the_session(client):
    client.post("/auth/login", json=LOGIN)
    client.post("/auth/logout")
    assert upload(client).status_code == 401


def test_forged_cookie_is_rejected(client):
    client.cookies.set(COOKIE, "recruiter:9999999999:" + "0" * 64)
    assert upload(client).status_code == 401


def test_without_demo_credentials_everything_is_open():
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    client = TestClient(app)
    assert client.get("/auth/session").json()["auth_required"] is False
    assert upload(client).status_code == 201

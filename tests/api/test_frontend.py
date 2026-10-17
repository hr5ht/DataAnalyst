from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_index_page_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="upload-form"' in response.text


def test_assets_are_served():
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").headers["content-type"].startswith("text/css")


def test_api_routes_still_take_priority():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/datasets/unknown").json() == {"detail": "Dataset not found."}

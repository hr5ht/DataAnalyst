from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_index_page_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="dropzone"' in response.text
    assert 'id="chat-form"' in response.text


def test_assets_are_served():
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").headers["content-type"].startswith("text/css")


def test_api_routes_still_take_priority():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/datasets/unknown").json() == {"detail": "Dataset not found."}


def test_page_has_the_question_form_and_a_pinned_chart_library():
    page = client.get("/").text
    assert "plotly.js-basic-dist-min@4.1.2/" in page
    assert 'integrity="sha384-' in page


def test_answers_are_rendered_as_text_only():
    script = client.get("/app.js").text
    for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert unsafe not in script


def test_sample_file_is_served_and_uploads():
    response = client.get("/sample.csv")
    assert response.status_code == 200
    upload = client.post("/datasets", files={"file": ("sample.csv", response.content, "text/csv")})
    assert upload.status_code == 201
    assert upload.json()["profile"]["rows"] == 14


def test_health_reports_the_upload_limit():
    assert client.get("/health").json()["max_upload_mb"] == 4


def test_page_has_a_login_form():
    page = client.get("/").text
    assert 'id="login-form"' in page
    assert 'type="password"' in page

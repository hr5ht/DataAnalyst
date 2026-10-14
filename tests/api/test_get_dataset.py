from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_dataset_returns_profile():
    created = client.post(
        "/datasets", files={"file": ("d.csv", b"a,b\n1,\n1,\n2,x\n", "text/csv")}
    ).json()
    response = client.get(f"/datasets/{created['dataset_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == created["dataset_id"]
    assert body["profile"] == created["profile"]
    assert body["profile"]["duplicate_rows"] == 1


def test_unknown_dataset_is_404():
    response = client.get("/datasets/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"] == "Dataset not found."

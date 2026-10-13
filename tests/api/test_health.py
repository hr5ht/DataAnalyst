import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def test_health_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret")
    settings = Settings(_env_file=None)
    assert settings.app_env == "test"
    assert settings.groq_api_key.get_secret_value() == "gsk_secret"
    assert "gsk_secret" not in repr(settings)


def test_settings_reject_unknown_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ValueError):
        Settings(_env_file=None)

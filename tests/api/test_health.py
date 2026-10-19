import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
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


@pytest.mark.parametrize(("key", "configured"), [(None, False), ("", False), ("gsk_secret", True)])
def test_health_reports_llm_configuration_without_leaking_the_key(key, configured):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, groq_api_key=key)
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["llm_configured"] is configured
    assert "gsk_secret" not in response.text

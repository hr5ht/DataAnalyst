import pytest
from langchain_groq import ChatGroq

from app.config import Settings
from app.llm import LLMError, get_chat_model


def settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_missing_key_gives_a_clear_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GROQ_API_KEY is not set") as error:
        get_chat_model(settings())
    assert error.value.retriable is False


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_key_counts_as_missing(blank):
    assert settings(groq_api_key=blank).groq_api_key is None


def test_model_is_built_from_settings():
    model = get_chat_model(
        settings(groq_api_key="gsk_test", groq_model="openai/gpt-oss-20b", llm_timeout_seconds=5, llm_max_retries=0)
    )
    assert isinstance(model, ChatGroq)
    assert model.model_name == "openai/gpt-oss-20b"
    assert model.temperature == pytest.approx(0, abs=1e-6)
    assert model.request_timeout == 5
    assert model.max_retries == 0
    assert model.groq_api_key.get_secret_value() == "gsk_test"
    assert "gsk_test" not in repr(model)


@pytest.mark.parametrize("kwargs", [{"llm_max_retries": 4}, {"llm_timeout_seconds": 0}])
def test_unbounded_retry_and_timeout_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        settings(**kwargs)

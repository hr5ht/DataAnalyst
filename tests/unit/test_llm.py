import groq
import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_groq import ChatGroq

from app.config import Settings
from app.llm import LLMError, get_chat_model, invoke_llm


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


REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def status_error(cls, code):
    return cls("provider said no to gsk_secret", response=httpx.Response(code, request=REQUEST), body=None)


class Failing:
    def __init__(self, error):
        self.error = error

    def invoke(self, prompt):
        raise self.error


def test_successful_call_returns_the_model_output():
    model = FakeListChatModel(responses=["Furniture"])
    assert invoke_llm(model, "Which category sold most?").content == "Furniture"


@pytest.mark.parametrize(
    ("error", "message", "retriable"),
    [
        (status_error(groq.RateLimitError, 429), "rate limit", True),
        (groq.APITimeoutError(request=REQUEST), "too long", True),
        (groq.APIConnectionError(request=REQUEST), "Could not reach", True),
        (status_error(groq.AuthenticationError, 401), "rejected the API key", False),
        (status_error(groq.PermissionDeniedError, 403), "rejected the API key", False),
        (status_error(groq.NotFoundError, 404), "GROQ_MODEL", False),
        (status_error(groq.InternalServerError, 503), "internal error", True),
        (status_error(groq.BadRequestError, 400), "HTTP 400", False),
    ],
)
def test_provider_errors_become_llm_errors(error, message, retriable):
    with pytest.raises(LLMError, match=message) as raised:
        invoke_llm(Failing(error), "hello")
    assert raised.value.retriable is retriable
    assert "gsk_secret" not in str(raised.value)
    assert raised.value.__cause__ is None

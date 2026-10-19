from typing import Any

import groq
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_groq import ChatGroq

from app.config import Settings


class LLMError(RuntimeError):
    def __init__(self, message: str, retriable: bool = False):
        super().__init__(message)
        self.retriable = retriable


def get_chat_model(settings: Settings) -> BaseChatModel:
    if settings.groq_api_key is None:
        raise LLMError("GROQ_API_KEY is not set, so questions can't be answered yet. Add it to .env and restart.")
    return ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=0,
    )


def invoke_llm(runnable: Runnable, prompt: Any) -> Any:
    try:
        return runnable.invoke(prompt)
    except groq.RateLimitError:
        raise LLMError("The LLM rate limit was reached. Wait a minute and try again.", retriable=True) from None
    except groq.APITimeoutError:
        raise LLMError("The LLM took too long to respond. Try again.", retriable=True) from None
    except groq.APIConnectionError:
        raise LLMError("Could not reach the LLM provider. Try again in a moment.", retriable=True) from None
    except (groq.AuthenticationError, groq.PermissionDeniedError):
        raise LLMError("The LLM provider rejected the API key. Check GROQ_API_KEY.") from None
    except groq.NotFoundError:
        raise LLMError("The configured GROQ_MODEL is not available.") from None
    except groq.InternalServerError:
        raise LLMError("The LLM provider had an internal error. Try again.", retriable=True) from None
    except groq.APIStatusError as error:
        raise LLMError(f"The LLM provider returned an error (HTTP {error.status_code}).") from None

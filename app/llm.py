from langchain_core.language_models import BaseChatModel
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

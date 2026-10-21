from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"

    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = Field(20, gt=0, le=120)
    llm_max_retries: int = Field(1, ge=0, le=3)

    embedding_model: str = "minishlab/potion-base-8M"

    max_upload_mb: float = Field(4, gt=0)
    max_rows: int = 200_000
    max_columns: int = 100

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def blank_key_is_missing(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

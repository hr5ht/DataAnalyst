from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    groq_api_key: SecretStr | None = None

    max_upload_mb: float = 10
    max_rows: int = 200_000
    max_columns: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()

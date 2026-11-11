"""Application settings, read from the .env file with pydantic-settings."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SQLITE_FALLBACK_URL = "sqlite:///memberplus.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Member+ API"
    environment: Literal["development", "production"] = "development"

    # Database. Empty = local SQLite fallback.
    database_url: str = ""

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # Session cookie
    cookie_name: str = "access_token"
    cookie_secure: bool = False

    # CORS: "http://a,http://b" in the .env
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def effective_database_url(self) -> str:
        return self.database_url or SQLITE_FALLBACK_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

"""Application settings, read from the .env file with pydantic-settings."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
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

    # Login brute-force protection (H4): after this many failed attempts for one
    # email, logins for it are blocked for the lockout time.
    login_max_attempts: int = Field(default=5, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)

    # Password for the demo users created by scripts/seed.py. Empty = known demo
    # password, allowed only in development.
    seed_password: str = ""

    # Object storage for images, through the S3 API (RustFS locally, any S3
    # provider in production). Empty endpoint = storage disabled: the API still
    # runs, logo uploads answer 503 and stored logos are reported as null.
    s3_endpoint_url: str = ""
    # Host the browser reaches for signed URLs. Inside Docker the API talks to
    # `http://storage:9000` but the browser needs `http://localhost:9000`.
    s3_public_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "memberplus"
    s3_region: str = "us-east-1"
    s3_url_expire_seconds: int = Field(default=3600, ge=60, le=604800)

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

    @property
    def storage_enabled(self) -> bool:
        return bool(self.s3_endpoint_url and self.s3_access_key and self.s3_secret_key)

    @property
    def effective_s3_public_endpoint_url(self) -> str:
        return self.s3_public_endpoint_url or self.s3_endpoint_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

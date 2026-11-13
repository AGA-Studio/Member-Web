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

    # Session cookie
    cookie_name: str = "access_token"
    cookie_secure: bool = False

    # CORS: "http://a,http://b" in the .env
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # Public base of the frontend: the card link is `{frontend_public_url}/tarjeta/<token>`.
    frontend_public_url: str = "http://localhost:3000"

    # Email (card link). Empty SMTP_HOST = no provider: in development the email is
    # logged and kept in memory; in production every send fails (`email_failed`).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: Literal["none", "starttls", "ssl"] = "starttls"
    smtp_timeout_seconds: float = Field(default=10, gt=0)
    mail_from: str = "no-reply@memberplus.mx"

    # Google Wallet. All of issuer, service account and logo are needed; with any
    # of them empty, the card page hides the button and the endpoint answers 503.
    google_wallet_issuer_id: str = ""
    google_wallet_service_account_json: str = ""
    google_wallet_origins: Annotated[list[str], NoDecode] = []
    google_wallet_logo_url: str = ""

    # Requests per minute and IP to the public card endpoints.
    card_rate_limit_per_minute: int = Field(default=30, ge=1)

    @field_validator("cors_origins", "google_wallet_origins", mode="before")
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

"""Unit tests for core/config.py."""

import pytest
from pydantic import ValidationError

from core.config import SQLITE_FALLBACK_URL, Settings


def make_settings(**overrides) -> Settings:
    # _env_file=None: ignore the developer's .env so tests are deterministic.
    return Settings(_env_file=None, **overrides)


def test_secret_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_empty_database_url_falls_back_to_sqlite() -> None:
    assert make_settings(secret_key="k", database_url="").effective_database_url == (
        SQLITE_FALLBACK_URL
    )


def test_database_url_is_used_when_present() -> None:
    url = "postgresql+psycopg://u:p@localhost:5433/db"
    assert make_settings(secret_key="k", database_url=url).effective_database_url == url


def test_cors_origins_are_split_by_comma(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test ,")
    assert make_settings(secret_key="k").cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_accept_a_list() -> None:
    assert make_settings(secret_key="k", cors_origins=["http://a.test"]).cors_origins == [
        "http://a.test"
    ]


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ALGORITHM", "ACCESS_TOKEN_EXPIRE_MINUTES", "COOKIE_SECURE", "ENVIRONMENT"):
        monkeypatch.delenv(var, raising=False)
    s = make_settings(secret_key="k")
    assert s.algorithm == "HS256"
    assert s.access_token_expire_minutes == 480
    assert s.cookie_name == "access_token"
    assert s.cookie_secure is False
    assert s.environment == "development"


def test_invalid_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(secret_key="k", environment="staging")

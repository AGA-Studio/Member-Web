"""Shared test fixtures.

Tests never touch the development database:
- By default they use a temporary SQLite file.
- Set TEST_DATABASE_URL to run them against a dedicated PostgreSQL database
  (it is wiped before every test).

Environment variables must be set before the app is imported, because
`core.config.settings` and `db.database.engine` are created at import time.
"""

import os
import tempfile
from collections.abc import Callable, Generator
from pathlib import Path

_tmp_db = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp_db}"
os.environ["SECRET_KEY"] = "test-only-secret-key-not-used-anywhere-else"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["COOKIE_SECURE"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from api.v1 import card_api  # noqa: E402
from core.security import hash_password  # noqa: E402
from db.database import engine  # noqa: E402
from main import app  # noqa: E402
from models import Business, BusinessStatus, Role, User  # noqa: E402
from services import email_service  # noqa: E402

DEFAULT_PASSWORD = "password123"
# Argon2id is slow on purpose; hash the shared password once per run.
_DEFAULT_HASH = hash_password(DEFAULT_PASSWORD)
LOGIN_URL = "/api/v1/auth/login"


@pytest.fixture(autouse=True)
def _clean_database() -> Generator[None]:
    """Every test starts with empty tables."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    # Pooled PostgreSQL connections keep prepared statements for the old tables
    # ("cached plan must not change result type"); start each test with fresh ones.
    engine.dispose()
    yield


@pytest.fixture(autouse=True)
def _reset_in_memory_state() -> Generator[None]:
    """The public card rate limit and the dev email outbox live in memory."""
    card_api.public_limiter.reset()
    email_service.OUTBOX.clear()
    yield


@pytest.fixture
def session() -> Generator[Session]:
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_business(session: Session) -> Callable[..., Business]:
    def factory(name: str = "Business", status: BusinessStatus = BusinessStatus.ACTIVE) -> Business:
        business = Business(name=name, status=status)
        session.add(business)
        session.commit()
        session.refresh(business)
        return business

    return factory


@pytest.fixture
def make_user(session: Session) -> Callable[..., User]:
    def factory(
        email: str,
        *,
        business: Business | None = None,
        role: Role = Role.ADMIN,
        password: str = DEFAULT_PASSWORD,
        is_active: bool = True,
        name: str = "Test User",
    ) -> User:
        hashed = _DEFAULT_HASH if password == DEFAULT_PASSWORD else hash_password(password)
        user = User(
            business_id=business.id if business else None,
            name=name,
            email=email,
            hashed_password=hashed,
            role=role,
            is_active=is_active,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    return factory


def login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> str:
    """Logs in (the client keeps the cookie) and returns the access token."""
    response = client.post(LOGIN_URL, data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def two_businesses(make_business, make_user) -> dict:
    """Scenario from the MVP demo: two businesses that must never see each other."""
    business_a = make_business("Business A")
    business_b = make_business("Business B")
    return {
        "business_a": business_a,
        "business_b": business_b,
        "admin_a": make_user("admin.a@demo.mx", business=business_a, role=Role.ADMIN),
        "employee_a": make_user("employee.a@demo.mx", business=business_a, role=Role.EMPLOYEE),
        "admin_b": make_user("admin.b@demo.mx", business=business_b, role=Role.ADMIN),
        "employee_b": make_user("employee.b@demo.mx", business=business_b, role=Role.EMPLOYEE),
        "platform": make_user("owner@memberplus.mx", business=None, role=Role.PLATFORM),
    }


# --- Object storage --------------------------------------------------------------

TEST_S3_ENDPOINT = "http://storage.test"
TEST_S3_PUBLIC_ENDPOINT = "http://localhost:9000"
TEST_S3_BUCKET = "memberplus-test"


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch):
    """S3 simulated in memory by moto; yields a boto3 client to inspect the bucket.

    The application's real boto3 code runs unchanged: only the server answering
    is fake, so CI needs no storage container.
    """
    from moto import mock_aws

    from core.config import settings
    from services import storage_service

    monkeypatch.setenv("MOTO_S3_CUSTOM_ENDPOINTS", TEST_S3_ENDPOINT)
    for name, value in {
        "s3_endpoint_url": TEST_S3_ENDPOINT,
        "s3_public_endpoint_url": TEST_S3_PUBLIC_ENDPOINT,
        "s3_access_key": "test-access",
        "s3_secret_key": "test-secret",
        "s3_bucket": TEST_S3_BUCKET,
    }.items():
        monkeypatch.setattr(settings, name, value)
    storage_service._client.cache_clear()
    storage_service._buckets_ready.clear()

    with mock_aws():
        yield storage_service._client(
            TEST_S3_ENDPOINT, "test-access", "test-secret", settings.s3_region
        )

    storage_service._client.cache_clear()
    storage_service._buckets_ready.clear()


def bucket_keys(client) -> set[str]:
    """Keys in the test bucket; a bucket never created (nothing stored yet) is empty."""
    try:
        response = client.list_objects_v2(Bucket=TEST_S3_BUCKET)
    except client.exceptions.NoSuchBucket:
        return set()
    return {item["Key"] for item in response.get("Contents", [])}


def make_image(
    fmt: str = "PNG", size: tuple[int, int] = (64, 48), mode: str = "RGB", **save
) -> bytes:
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new(mode, size, "teal" if mode != "1" else 1).save(output, format=fmt, **save)
    return output.getvalue()

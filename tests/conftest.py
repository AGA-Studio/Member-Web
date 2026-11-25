"""Shared test fixtures.

Tests never touch the development database:
- By default they use a temporary SQLite file, one per pytest worker.
- Set TEST_DATABASE_URL to run them against a dedicated PostgreSQL database
  (it is wiped before every test).

Environment variables must be set before the app is imported, because
`core.config.settings` and `db.database.engine` are created at import time.
"""

import os
import tempfile
from collections.abc import Callable, Generator
from pathlib import Path

# One file per worker: `pytest -n auto --dist loadfile` runs several processes
# at once, and a shared file would let them clobber each other's tables.
_worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
_tmp_db = Path(tempfile.mkdtemp()) / f"test-{_worker}.db"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp_db}"
os.environ["SECRET_KEY"] = "test-only-secret-key-not-used-anywhere-else"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["COOKIE_SECURE"] = "false"
# Empty = no provider: the card email goes to `email_service.OUTBOX`, as the
# tests expect. A developer's `.env` pointing at Mailpit would send for real.
os.environ["SMTP_HOST"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pwdlib import PasswordHash  # noqa: E402
from pwdlib.hashers.argon2 import Argon2Hasher  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.exc import OperationalError, ProgrammingError  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from api.v1 import card_api, public_api, registration_api  # noqa: E402
from core import security  # noqa: E402
from core.security import hash_password  # noqa: E402
from db import rls  # noqa: E402
from db.database import engine  # noqa: E402
from main import app  # noqa: E402
from models import Business, BusinessStatus, Role, User  # noqa: E402
from services import email_service, plan_service  # noqa: E402

# Cheaper Argon2id parameters for the suite: these are still real `$argon2id$`
# hashes, only with a smaller cost. The API logs in around 360 times across the
# tests and each verification at production cost takes ~48 ms, which is nearly
# 20 s of pure CPU. `tests/unit/test_security.py` tests the hashing itself and
# still passes; production keeps the `pwdlib` defaults in core/security.py.
security.password_hash = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8192, parallelism=1),))

DEFAULT_PASSWORD = "password123"
# Argon2id is slow on purpose; hash the shared password once per run.
_DEFAULT_HASH = hash_password(DEFAULT_PASSWORD)
LOGIN_URL = "/api/v1/auth/login"

# SQLite flushes to disk (fsync twice) on every statement that writes, and the
# suite writes a lot before every test: ~40 flushes, ~500 ms per test on a
# normal disk. This database is deleted when the run ends, so durability buys
# nothing here; keeping the journal in memory and skipping the flush makes the
# same work ~45x faster without changing what the tests verify. `synchronous`
# is per connection, so the pragmas have to be applied on connect.
if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _fast_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=MEMORY")
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.close()


@pytest.fixture(scope="session", autouse=True)
def _database_schema() -> Generator[None]:
    """Create the schema once per run; every test only clears the rows.

    Rebuilding the ten tables per test was the most expensive part of a test
    (~8 ms of DDL on SQLite, ~120 ms of catalog work on PostgreSQL). Nothing
    survives between tests anyway: the rows are deleted and the in-memory
    state (rate limits, email outbox) is reset by their own fixtures.
    """
    if engine.dialect.name == "postgresql":
        _create_postgres_schema()
        engine.dispose()
    else:
        SQLModel.metadata.create_all(engine)
    yield


def _create_postgres_schema() -> None:
    """`create_all` plus the Row Level Security that the migration adds.

    Without the policies the whole suite would pass on PostgreSQL even if a
    request broke because of RLS; with them, every API test runs under it.
    """
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        for statement in rls.enable_statements():
            connection.execute(text(statement))


def _truncate_tables() -> None:
    """Empty every table in a single statement, resetting the identifiers.

    One `TRUNCATE` instead of twenty DDL statements: on PostgreSQL the cost of
    `drop_all` + `create_all` is catalog work (~120 ms per test), not disk.
    Raises if the tables are not the ones `create_all` builds, which is the
    state `tests/db/test_migrations.py` leaves behind.
    """
    tables = ", ".join(f'"{table.name}"' for table in SQLModel.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def _delete_sqlite_rows() -> None:
    """Empty every table in reverse dependency order, with no DDL at all.

    ~0.3 ms against ~8 ms for `drop_all` + `create_all`. A plain `DELETE`
    leaves the rowids restarting from 1, so tests that read ids still see the
    numbers they would see on a freshly recreated schema.
    """
    with engine.begin() as connection:
        for table in reversed(SQLModel.metadata.sorted_tables):
            connection.execute(text(f'DELETE FROM "{table.name}"'))


@pytest.fixture
def _clean_database() -> Generator[None]:
    """Every test that opens a session starts with empty tables.

    Deliberately not `autouse`: a unit test that never touches the database has
    no reason to pay for the cleanup. `session` and `client` request this
    fixture, so any test using the database gets it.
    """
    if engine.dialect.name == "postgresql":
        try:
            _truncate_tables()
        except ProgrammingError:
            # The migrations tests dropped the tables and rebuilt them with
            # Alembic: restore the schema `create_all` produces before going on.
            SQLModel.metadata.drop_all(engine)
            _create_postgres_schema()
        _load_plan_catalog()
        yield
        return

    try:
        _delete_sqlite_rows()
    except OperationalError:
        # Same case on SQLite: the tables are missing (the migrations tests
        # removed them) or are not the ones the models describe.
        SQLModel.metadata.drop_all(engine)
        SQLModel.metadata.create_all(engine)
    _load_plan_catalog()
    yield


def _load_plan_catalog() -> None:
    """The plans are data the migration loads; `create_all` leaves them empty."""
    with Session(engine) as db_session:
        plan_service.ensure_catalog(db_session)


@pytest.fixture(autouse=True)
def _reset_in_memory_state() -> Generator[None]:
    """The public rate limits and the dev email outbox live in memory."""
    card_api.public_limiter.reset()
    public_api.asset_limiter.reset()
    registration_api.registration_limiter.reset()
    email_service.OUTBOX.clear()
    yield


@pytest.fixture
def session(_clean_database: None) -> Generator[Session]:
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def client(_clean_database: None) -> Generator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_business(session: Session) -> Callable[..., Business]:
    def factory(
        name: str = "Business",
        status: BusinessStatus = BusinessStatus.ACTIVE,
        plan: str | None = "chain",
    ) -> Business:
        """`plan` is a catalog key; the biggest by default, so a test about
        anything else never hits a plan limit. `None` = no plan (the default)."""
        plan_row = plan_service.get_by_key(session, plan) if plan else None
        business = Business(name=name, status=status, plan_id=plan_row.id if plan_row else None)
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
def two_businesses(session: Session) -> dict:
    """Scenario from the MVP demo: two businesses that must never see each other.

    One `flush` so the users can reference the business ids and one `commit`
    for everything: seven commits per test, over ~400 tests, was a measurable
    part of the suite.
    """
    # The biggest plan, like `make_business`: tests about plan limits set their own.
    top_plan = plan_service.get_by_key(session, "chain").id
    business_a = Business(name="Business A", status=BusinessStatus.ACTIVE, plan_id=top_plan)
    business_b = Business(name="Business B", status=BusinessStatus.ACTIVE, plan_id=top_plan)
    session.add_all([business_a, business_b])
    session.flush()

    admin_a = User(
        business_id=business_a.id,
        name="Test User",
        email="admin.a@demo.mx",
        hashed_password=_DEFAULT_HASH,
        role=Role.ADMIN,
        is_active=True,
    )
    employee_a = User(
        business_id=business_a.id,
        name="Test User",
        email="employee.a@demo.mx",
        hashed_password=_DEFAULT_HASH,
        role=Role.EMPLOYEE,
        is_active=True,
    )
    admin_b = User(
        business_id=business_b.id,
        name="Test User",
        email="admin.b@demo.mx",
        hashed_password=_DEFAULT_HASH,
        role=Role.ADMIN,
        is_active=True,
    )
    employee_b = User(
        business_id=business_b.id,
        name="Test User",
        email="employee.b@demo.mx",
        hashed_password=_DEFAULT_HASH,
        role=Role.EMPLOYEE,
        is_active=True,
    )
    platform = User(
        business_id=None,
        name="Test User",
        email="owner@memberplus.mx",
        hashed_password=_DEFAULT_HASH,
        role=Role.PLATFORM,
        is_active=True,
    )
    session.add_all([admin_a, employee_a, admin_b, employee_b, platform])
    session.commit()
    return {
        "business_a": business_a,
        "business_b": business_b,
        "admin_a": admin_a,
        "employee_a": employee_a,
        "admin_b": admin_b,
        "employee_b": employee_b,
        "platform": platform,
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

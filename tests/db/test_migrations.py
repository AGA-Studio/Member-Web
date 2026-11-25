"""Alembic migrations: they apply, revert, and match the SQLModel models.

Runs on the same database as the rest of the suite (SQLite, or PostgreSQL when
TEST_DATABASE_URL is set).
"""

from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import Connection, inspect, text
from sqlmodel import Session, SQLModel

from db.database import engine
from models import Business, Role, User
from tests.conftest import _DEFAULT_HASH, login

ROOT = Path(__file__).resolve().parents[2]
APP_TABLES = {
    "businesses",
    "users",
    "revoked_tokens",
    "login_attempts",
    "tiers",
    "customers",
    "purchases",
    "card_deliveries",
    "card_emails",
    "membership_payments",
    "plans",
}


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def run(action: str, revision: str) -> None:
    with engine.begin() as connection:
        getattr(command, action)(alembic_config(connection), revision)


def table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def enum_types() -> set[str]:
    if engine.dialect.name != "postgresql":
        return set()
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
        return {row[0] for row in rows}


@pytest.fixture
def empty_database(_clean_database: None) -> Generator[None]:
    """Start from a database with no tables at all (not even alembic_version).

    Depends on `_clean_database` so the shared cleanup runs first and this
    fixture always ends up dropping whatever the previous test left behind.
    """
    SQLModel.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    yield
    # Leave the database empty on purpose: the tables this test created came
    # from Alembic, and the rest of the suite expects the schema `create_all`
    # builds. With no tables, the next `_clean_database` falls back to
    # `drop_all` + `create_all` and normalizes it.
    SQLModel.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()


def test_there_is_a_single_head() -> None:
    # Two heads = two people created migrations in parallel; they must be merged.
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert len(heads) == 1, f"Multiple Alembic heads: {heads}"


def test_upgrade_creates_all_tables(empty_database) -> None:
    run("upgrade", "head")
    assert table_names() == APP_TABLES | {"alembic_version"}


def test_models_and_migrations_are_in_sync(empty_database) -> None:
    """Fails when a model changed and nobody generated the migration."""
    run("upgrade", "head")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, SQLModel.metadata)
    assert differences == [], (
        "Models differ from migrations. Run:\n"
        '  uv run alembic revision --autogenerate -m "describe the change"\n'
        f"Differences: {differences}"
    )


def test_downgrade_removes_tables_and_enums(empty_database) -> None:
    run("upgrade", "head")
    run("downgrade", "base")
    assert table_names() == {"alembic_version"}
    assert enum_types() & {"role", "businessstatus", "tierfinish"} == set()


def test_upgrade_after_downgrade(empty_database) -> None:
    run("upgrade", "head")
    run("downgrade", "base")
    run("upgrade", "head")
    assert table_names() == APP_TABLES | {"alembic_version"}


def test_database_is_stamped_at_head(empty_database) -> None:
    run("upgrade", "head")
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == head


def test_app_works_on_migrated_schema(empty_database, client: TestClient) -> None:
    """The API runs on tables created by Alembic, not only by create_all."""
    run("upgrade", "head")
    with Session(engine) as session:
        business = Business(name="Migrated")
        session.add(business)
        session.commit()
        session.add(
            User(
                business_id=business.id,
                name="Admin",
                email="admin@migrated.mx",
                hashed_password=_DEFAULT_HASH,
                role=Role.ADMIN,
            )
        )
        session.commit()

    login(client, "admin@migrated.mx")
    response = client.post(
        "/api/v1/user/create",
        json={"name": "Cashier", "email": "cashier@migrated.mx", "password": "password123"},
    )
    assert response.status_code == 201
    assert len(client.get("/api/v1/user/list").json()) == 2


def raw_enum_values() -> tuple[set[str], set[str]]:
    with engine.connect() as connection:
        roles = {row[0] for row in connection.execute(text("SELECT role FROM users"))}
        statuses = {row[0] for row in connection.execute(text("SELECT status FROM businesses"))}
    return roles, statuses


def test_lowercase_enum_migration_converts_existing_rows(empty_database) -> None:
    """H7: rows written by the first migration (uppercase) become lowercase."""
    run("upgrade", "f689e0ec2cd6")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses (name, status, created_at) "
                "VALUES ('Old', 'SUSPENDED', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO users (business_id, name, email, hashed_password, role, is_active, "
                "created_at) VALUES (1, 'Old', 'old@demo.mx', 'h', 'ADMIN', true, "
                "CURRENT_TIMESTAMP)"
            )
        )

    run("upgrade", "head")
    assert raw_enum_values() == ({"admin"}, {"suspended"})

    run("downgrade", "f689e0ec2cd6")
    assert raw_enum_values() == ({"ADMIN"}, {"SUSPENDED"})


def test_app_stores_lowercase_enum_values(empty_database) -> None:
    run("upgrade", "head")
    with Session(engine) as session:
        business = Business(name="New")
        session.add(business)
        session.commit()
        session.add(
            User(
                business_id=business.id,
                name="Emp",
                email="emp@new.mx",
                hashed_password=_DEFAULT_HASH,
            )
        )
        session.commit()
    assert raw_enum_values() == ({"employee"}, {"trial"})


def test_plans_migration_keeps_existing_businesses_open(empty_database) -> None:
    """Businesses created before the plans go to `business` without a trial (issue #70)."""
    run("upgrade", "0fad7d4917d8")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses (name, status, validity_months, created_at) "
                "VALUES ('Old', 'active', 12, CURRENT_TIMESTAMP)"
            )
        )

    run("upgrade", "head")
    with engine.connect() as connection:
        plans = connection.execute(text("SELECT key, is_default FROM plans ORDER BY sort_order"))
        assert [tuple(row) for row in plans] == [
            ("free", True),
            ("counter", False),
            ("business", False),
            ("chain", False),
        ]
        row = connection.execute(
            text(
                "SELECT p.key, b.trial_ends_at, b.unit_price_cents "
                "FROM businesses b JOIN plans p ON p.id = b.plan_id"
            )
        ).one()
    assert tuple(row) == ("business", None, 39_900)


def test_manager_role_downgrade_turns_managers_into_employees(empty_database) -> None:
    """PostgreSQL cannot drop an enum value: going back must not leave a manager behind."""
    run("upgrade", "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses (name, status, validity_months, created_at) "
                "VALUES ('B', 'active', 12, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO users (business_id, name, email, hashed_password, role, is_active, "
                "created_at) VALUES (1, 'Mgr', 'mgr@demo.mx', 'h', 'manager', true, "
                "CURRENT_TIMESTAMP)"
            )
        )

    run("downgrade", "e4a7b9c1d3f5")
    roles, _ = raw_enum_values()
    assert roles == {"employee"}

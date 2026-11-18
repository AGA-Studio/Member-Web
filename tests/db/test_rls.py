"""Row Level Security on PostgreSQL (db/rls.py, issue #74).

These tests query the database directly, without the application's
`business_id` filter: they prove PostgreSQL itself hides the other business.
On SQLite (no RLS) only the activation is checked.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from db import rls
from db.database import engine
from models import Business, Customer, Tier, User
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

postgres_only = pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Row Level Security exists only in PostgreSQL"
)


@pytest.fixture
def data(session: Session, two_businesses) -> dict:
    a, b = two_businesses["business_a"], two_businesses["business_b"]
    tier_a = add_tier(session, a, "Oro A", 0)
    tier_b = add_tier(session, b, "Oro B", 0)
    add_customer(session, a, tier_a, "Laura Méndez", code="MP-AAAA1")
    add_customer(session, b, tier_b, "Pedro Ruiz", code="MP-BBBB1")
    return {"a": a.id, "b": b.id, "tier_b": tier_b.id}


def test_activate_records_the_business(session: Session) -> None:
    rls.activate(session, 7)
    assert session.info["rls_business_id"] == 7


@postgres_only
class TestPolicies:
    def test_scoped_session_sees_only_its_business(self, data: dict) -> None:
        with Session(engine) as scoped:
            rls.activate(scoped, data["a"])
            # No WHERE business_id: the filter comes from the database.
            assert [c.full_name for c in scoped.exec(select(Customer))] == ["Laura Méndez"]
            assert [t.name for t in scoped.exec(select(Tier))] == ["Oro A"]
            assert [b.id for b in scoped.exec(select(Business))] == [data["a"]]
            users = scoped.exec(select(User)).all()
            assert users and {u.business_id for u in users} == {data["a"]}

    def test_a_row_of_another_business_is_not_found(self, data: dict) -> None:
        with Session(engine) as scoped:
            rls.activate(scoped, data["a"])
            assert scoped.get(Tier, data["tier_b"]) is None

    def test_cannot_write_into_another_business(self, data: dict) -> None:
        with Session(engine) as scoped:
            rls.activate(scoped, data["a"])
            scoped.add(Tier(business_id=data["b"], name="Intruso", price_cents=0))
            with pytest.raises(DBAPIError, match="row-level security"):
                scoped.commit()

    def test_cannot_move_a_row_to_another_business(self, data: dict) -> None:
        with Session(engine) as scoped:
            rls.activate(scoped, data["a"])
            with pytest.raises(DBAPIError, match="row-level security"):
                scoped.execute(
                    text("UPDATE tiers SET business_id = :b WHERE business_id = :a"),
                    {"a": data["a"], "b": data["b"]},
                )

    def test_scope_survives_a_commit(self, data: dict) -> None:
        """The next transaction is scoped again (`after_begin`)."""
        with Session(engine) as scoped:
            rls.activate(scoped, data["a"])
            scoped.commit()
            assert len(scoped.exec(select(Customer)).all()) == 1
            scoped.rollback()
            assert len(scoped.exec(select(Customer)).all()) == 1

    def test_tenant_role_without_business_sees_nothing(self, data: dict) -> None:
        """Fail closed: the role alone, with no business set, matches no row."""
        with engine.begin() as connection:
            connection.execute(text(f"SET LOCAL ROLE {rls.TENANT_ROLE}"))
            assert connection.execute(text("SELECT count(*) FROM customers")).scalar() == 0

    def test_the_setting_does_not_leak_to_the_next_session(self, data: dict) -> None:
        with Session(engine) as scoped:
            rls.activate(scoped, data["a"])
            scoped.exec(select(Customer)).all()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_user")).scalar() != rls.TENANT_ROLE
            assert connection.execute(text("SELECT count(*) FROM customers")).scalar() == 2

    def test_unscoped_session_sees_every_business(self, data: dict) -> None:
        """Login, the public card and the platform run without a business."""
        with Session(engine) as owner:
            assert len(owner.exec(select(Customer)).all()) == 2

    def test_api_requests_run_under_the_tenant_role(self, client: TestClient, data) -> None:
        login(client, "admin.a@demo.mx")
        statements: list[str] = []

        def record(_conn, _cursor, statement, *_args) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            body = client.get("/api/v1/customer/list").json()
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert [item["full_name"] for item in body["items"]] == ["Laura Méndez"]
        assert f"SET LOCAL ROLE {rls.TENANT_ROLE}" in statements

    def test_login_and_public_routes_stay_unscoped(self, client: TestClient, data) -> None:
        """Login looks the user up across businesses: it must not take the role."""
        statements: list[str] = []

        def record(_conn, _cursor, statement, *_args) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            login(client, "admin.b@demo.mx")
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert not any("SET LOCAL ROLE" in statement for statement in statements)

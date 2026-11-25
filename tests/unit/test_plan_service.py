"""Plan catalog and effective plan (services/plan_service.py, issue #70)."""

from datetime import timedelta

from sqlmodel import Session, select

from models import Business, Plan
from services import plan_service
from services.customer_service import utc_now


def plan(session: Session, key: str) -> Plan:
    found = plan_service.get_by_key(session, key)
    assert found is not None
    return found


class TestCatalog:
    def test_exactly_one_default_plan(self) -> None:
        assert [row["key"] for row in plan_service.CATALOG if row["is_default"]] == ["free"]

    def test_keys_are_unique(self) -> None:
        keys = [row["key"] for row in plan_service.CATALOG]
        assert len(keys) == len(set(keys))

    def test_ensure_catalog_is_idempotent(self, session: Session) -> None:
        plan_service.ensure_catalog(session)
        plan_service.ensure_catalog(session)
        assert len(session.exec(select(Plan)).all()) == len(plan_service.CATALOG)

    def test_ensure_catalog_never_overwrites_an_edited_plan(self, session: Session) -> None:
        free = plan(session, "free")
        free.max_customers = 80
        session.add(free)
        session.commit()
        plan_service.ensure_catalog(session)
        session.refresh(free)
        assert free.max_customers == 80

    def test_public_plans_hide_the_ones_assigned_by_hand(self, session: Session) -> None:
        keys = [p.key for p in plan_service.public_plans(session)]
        assert keys == ["free", "counter", "business"]


class TestEffectivePlan:
    def test_no_plan_is_the_default(self, session: Session, make_business) -> None:
        business = make_business(plan=None)
        assert business.plan_id is None
        assert plan_service.effective_plan(session, business).key == "free"

    def test_assigned_plan_without_trial(self, session: Session, make_business) -> None:
        business = make_business()
        business.plan_id = plan(session, "counter").id
        assert plan_service.effective_plan(session, business).key == "counter"

    def test_trial_in_progress_gives_the_plan(self, session: Session, make_business) -> None:
        business = make_business()
        business.plan_id = plan(session, "business").id
        business.trial_ends_at = utc_now() + timedelta(days=3)
        assert plan_service.trial_active(business)
        assert plan_service.effective_plan(session, business).key == "business"

    def test_ended_trial_falls_back_to_the_default(self, session: Session, make_business) -> None:
        """Computed when read: no job moves the business, nothing else changes."""
        business = make_business()
        business.plan_id = plan(session, "business").id
        business.trial_ends_at = utc_now() - timedelta(seconds=1)
        session.add(business)
        session.commit()
        assert plan_service.effective_plan(session, business).key == "free"
        session.refresh(business)
        assert business.plan_id == plan(session, "business").id

    def test_works_with_the_date_read_back(self, session: Session, make_business) -> None:
        """SQLite returns the date without a time zone: it is read as UTC."""
        business = make_business()
        business.plan_id = plan(session, "business").id
        business.trial_ends_at = utc_now() + timedelta(days=1)
        session.add(business)
        session.commit()
        session.refresh(business)
        assert plan_service.effective_plan(session, business).key == "business"

    def test_a_plan_does_not_change_the_access(self, session: Session, make_business) -> None:
        """`status` is access, the plan is capabilities."""
        business = make_business()
        business.plan_id = plan(session, "business").id
        business.trial_ends_at = utc_now() - timedelta(days=1)
        status_before = business.status
        plan_service.effective_plan(session, business)
        assert business.status == status_before
        assert isinstance(business, Business)

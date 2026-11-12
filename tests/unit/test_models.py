"""Model defaults and database constraints."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from models import Business, BusinessStatus, Role, User


def test_business_defaults(session: Session) -> None:
    business = Business(name="Shop")
    session.add(business)
    session.commit()
    session.refresh(business)
    assert business.id is not None
    assert business.status == BusinessStatus.TRIAL
    assert business.logo_url is None
    assert business.created_at is not None


def test_user_defaults(session: Session, make_business) -> None:
    user = User(business_id=make_business().id, name="U", email="u@demo.mx", hashed_password="h")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.role == Role.EMPLOYEE
    assert user.is_active is True


def test_email_unique_constraint(session: Session, make_business) -> None:
    business_id = make_business().id
    session.add(User(business_id=business_id, name="A", email="dup@demo.mx", hashed_password="h"))
    session.commit()
    session.add(User(business_id=business_id, name="B", email="dup@demo.mx", hashed_password="h"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_enum_values() -> None:
    assert [r.value for r in Role] == ["platform", "admin", "employee"]
    assert [s.value for s in BusinessStatus] == ["trial", "active", "suspended"]

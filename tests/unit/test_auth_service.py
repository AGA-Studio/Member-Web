"""Unit tests for services/auth_service.py: token revocation (H2)."""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from models import RevokedToken
from services.auth_service import is_token_revoked, purge_expired_revocations, revoke_token


def future(minutes: int = 60) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def test_revoked_token_is_detected(session: Session) -> None:
    assert is_token_revoked(session, "abc") is False
    revoke_token(session, "abc", future())
    assert is_token_revoked(session, "abc") is True


def test_revoke_is_idempotent(session: Session) -> None:
    revoke_token(session, "abc", future())
    revoke_token(session, "abc", future())
    assert len(session.exec(select(RevokedToken)).all()) == 1


def test_expired_revocations_are_purged(session: Session) -> None:
    session.add(RevokedToken(jti="old", expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    session.add(RevokedToken(jti="live", expires_at=future()))
    session.commit()

    purge_expired_revocations(session)
    session.commit()

    assert {row.jti for row in session.exec(select(RevokedToken)).all()} == {"live"}


def test_logout_purges_old_rows(session: Session) -> None:
    session.add(RevokedToken(jti="old", expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    session.commit()
    revoke_token(session, "new", future())
    assert {row.jti for row in session.exec(select(RevokedToken)).all()} == {"new"}

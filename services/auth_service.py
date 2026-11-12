"""Authentication rules that need the database.

- Token revocation on logout (H2).
- Failed-login limit per email (H4).
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, delete

from core.config import settings
from models.login_attempt_model import LoginAttempt
from models.revoked_token_model import RevokedToken


def revoke_token(session: Session, jti: str, expires_at: datetime) -> None:
    """Invalidate one token (logout). Idempotent: revoking twice is harmless."""
    purge_expired_revocations(session)
    if session.get(RevokedToken, jti) is None:
        session.add(RevokedToken(jti=jti, expires_at=expires_at))
    session.commit()


def is_token_revoked(session: Session, jti: str) -> bool:
    return session.get(RevokedToken, jti) is not None


def purge_expired_revocations(session: Session) -> None:
    """Expired tokens are rejected by their signature anyway; drop their rows."""
    session.exec(delete(RevokedToken).where(RevokedToken.expires_at < datetime.now(UTC)))


# --- Failed-login limit (H4) -----------------------------------------------------


def _now() -> datetime:
    # A function (not datetime.now inline) so tests can move the clock.
    return datetime.now(UTC)


def _lockout() -> timedelta:
    return timedelta(minutes=settings.login_lockout_minutes)


def login_retry_after(session: Session, email: str) -> int | None:
    """Seconds until `email` may try again, or None if it is not locked."""
    attempt = session.get(LoginAttempt, email)
    if attempt is None or attempt.locked_until is None:
        return None
    remaining = (attempt.locked_until - _now()).total_seconds()
    return max(1, int(remaining) + 1) if remaining > 0 else None


def register_failed_login(session: Session, email: str) -> None:
    """Count one failure; lock the email once it reaches `login_max_attempts`."""
    now = _now()
    # Rows nobody touched within the window carry no information anymore.
    session.exec(
        delete(LoginAttempt).where(
            LoginAttempt.last_failed_at < now - _lockout(), LoginAttempt.email != email
        )
    )
    attempt = session.get(LoginAttempt, email)
    if attempt is None:
        attempt = LoginAttempt(email=email, last_failed_at=now)
    elif now - attempt.last_failed_at > _lockout():
        # Old failures (or an expired lock) no longer count.
        attempt.failed_count = 0
        attempt.locked_until = None

    attempt.failed_count += 1
    attempt.last_failed_at = now
    if attempt.failed_count >= settings.login_max_attempts:
        attempt.locked_until = now + _lockout()
    session.add(attempt)
    session.commit()


def clear_failed_logins(session: Session, email: str) -> None:
    """A correct password resets the counter."""
    attempt = session.get(LoginAttempt, email)
    if attempt is not None:
        session.delete(attempt)
        session.commit()

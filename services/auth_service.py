"""Authentication rules that need the database: token revocation (H2)."""

from datetime import UTC, datetime

from sqlmodel import Session, delete

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

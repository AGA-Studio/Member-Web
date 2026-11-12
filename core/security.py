"""Password hashing with Argon2id and JWT creation/decoding."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from core.config import settings

# Argon2Hasher uses the Argon2id variant by default.
password_hash = PasswordHash((Argon2Hasher(),))


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def create_access_token(
    *, user_id: int, role: str, business_id: int | None, expires_delta: timedelta | None = None
) -> str:
    """The token carries the user's business: the only valid source of `business_id`.

    `jti` is a unique id per token, so a single session can be revoked on logout.
    """
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "business_id": business_id,
        "exp": expire,
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError if the token is invalid or expired."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

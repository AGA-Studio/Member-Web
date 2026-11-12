"""Unit tests for core/security.py: Argon2id hashing and JWT."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from core.config import settings
from core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

OTHER_KEY = "another-key-that-is-at-least-32-bytes-long"


class TestPasswordHashing:
    def test_hash_uses_argon2id(self) -> None:
        assert hash_password("password123").startswith("$argon2id$")

    def test_hash_never_stores_plain_text(self) -> None:
        assert "password123" not in hash_password("password123")

    def test_same_password_produces_different_hashes(self) -> None:
        # Random salt per hash.
        assert hash_password("password123") != hash_password("password123")

    def test_verify_correct_password(self) -> None:
        hashed = hash_password("password123")
        assert verify_password("password123", hashed) is True

    def test_verify_wrong_password(self) -> None:
        hashed = hash_password("password123")
        assert verify_password("password124", hashed) is False

    def test_verify_is_case_sensitive(self) -> None:
        hashed = hash_password("Password123")
        assert verify_password("password123", hashed) is False

    def test_unicode_password(self) -> None:
        hashed = hash_password("contraseña-ñandú-🔒")
        assert verify_password("contraseña-ñandú-🔒", hashed) is True


class TestAccessToken:
    def test_token_contains_expected_claims(self) -> None:
        token = create_access_token(user_id=7, role="admin", business_id=3)
        payload = decode_access_token(token)
        assert payload["sub"] == "7"
        assert payload["role"] == "admin"
        assert payload["business_id"] == 3
        assert "exp" in payload

    def test_platform_token_has_null_business(self) -> None:
        token = create_access_token(user_id=1, role="platform", business_id=None)
        assert decode_access_token(token)["business_id"] is None

    def test_default_expiration_matches_settings(self) -> None:
        before = datetime.now(UTC)
        token = create_access_token(user_id=1, role="admin", business_id=1)
        exp = datetime.fromtimestamp(decode_access_token(token)["exp"], UTC)
        expected = before + timedelta(minutes=settings.access_token_expire_minutes)
        assert abs((exp - expected).total_seconds()) < 5

    def test_custom_expiration(self) -> None:
        token = create_access_token(
            user_id=1, role="admin", business_id=1, expires_delta=timedelta(minutes=5)
        )
        exp = datetime.fromtimestamp(decode_access_token(token)["exp"], UTC)
        assert timedelta(minutes=4) < exp - datetime.now(UTC) <= timedelta(minutes=5)

    def test_expired_token_is_rejected(self) -> None:
        token = create_access_token(
            user_id=1, role="admin", business_id=1, expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_tampered_token_is_rejected(self) -> None:
        token = create_access_token(user_id=1, role="employee", business_id=1)
        header, payload, signature = token.split(".")
        forged = jwt.encode(
            {"sub": "1", "role": "admin", "business_id": 2}, "k" * 32, algorithm="HS256"
        ).split(".")[1]
        with pytest.raises(jwt.InvalidSignatureError):
            decode_access_token(f"{header}.{forged}.{signature}")

    def test_token_signed_with_another_key_is_rejected(self) -> None:
        token = jwt.encode(
            {"sub": "1", "role": "admin", "business_id": 1}, OTHER_KEY, algorithm="HS256"
        )
        with pytest.raises(jwt.InvalidSignatureError):
            decode_access_token(token)

    def test_unsigned_token_alg_none_is_rejected(self) -> None:
        token = jwt.encode({"sub": "1", "role": "admin", "business_id": 1}, None, algorithm="none")
        with pytest.raises(jwt.InvalidAlgorithmError):
            decode_access_token(token)

    def test_garbage_token_is_rejected(self) -> None:
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token("not-a-jwt")

"""Router for /api/v1/auth: login, logout and current session."""

from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from api.v1.dependencies import (
    CurrentUser,
    SessionDep,
    ensure_user_can_access,
    get_request_token,
)
from core.config import settings
from core.errors import ApiError, ErrorCode
from core.security import create_access_token, decode_access_token, verify_password
from models.business_model import Business
from models.user_model import User
from schemas.token_schema import Token
from schemas.user_schema import MeResponse, UserResponse
from services import logo_service
from services.auth_service import (
    clear_failed_logins,
    login_retry_after,
    register_failed_login,
    revoke_token,
)
from services.turnstile_service import verify_turnstile

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(
    response: Response,
    session: SessionDep,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    turnstile_token: Annotated[str | None, Header(alias="X-Turnstile-Token")] = None,
) -> Token:
    """Log in with email (`username` field) and password.

    Sets the JWT in an httpOnly cookie for the frontend and also returns it in the
    body for Swagger and the cashier reader. With `TURNSTILE_ENABLED`, the
    `X-Turnstile-Token` header is required (400 `turnstile_failed`).
    """
    # Turnstile goes first: a bot that fails it never reaches the H4 counter, so it
    # cannot lock a real user's email.
    if not verify_turnstile(turnstile_token):
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="turnstile_failed",
            code=ErrorCode.TURNSTILE_FAILED,
        )

    email = form.username.lower()

    # H4: after `login_max_attempts` failures the email is locked, even for the right
    # password; otherwise the lock would not stop a brute-force attack.
    retry_after = login_retry_after(session, email)
    if retry_after is not None:
        raise ApiError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            code=ErrorCode.LOGIN_LOCKED,
            headers={"Retry-After": str(retry_after)},
        )

    user = session.exec(select(User).where(User.email == email)).first()
    if user is None or not verify_password(form.password, user.hashed_password):
        register_failed_login(session, email)
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            code=ErrorCode.INVALID_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )
    clear_failed_logins(session, email)
    ensure_user_can_access(session, user)

    token = create_access_token(user_id=user.id, role=user.role, business_id=user.business_id)
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )
    return Token(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: SessionDep,
    token: Annotated[str | None, Depends(get_request_token)],
) -> None:
    """Close this session: revoke its token (cookie or Bearer) and delete the cookie.

    Other sessions of the same user stay open. Always 204, even without a valid
    token, so logging out never fails.
    """
    if token:
        try:
            payload = decode_access_token(token)
            expires_at = datetime.fromtimestamp(payload["exp"], UTC)
            revoke_token(session, payload["jti"], expires_at)
        except jwt.InvalidTokenError, KeyError:
            pass  # Invalid or expired token: nothing to revoke.
    response.delete_cookie(settings.cookie_name)


@router.get("/me", response_model=MeResponse)
def me(session: SessionDep, user: CurrentUser) -> MeResponse:
    """Session user and their business (null for the platform owner)."""
    business = session.get(Business, user.business_id) if user.business_id is not None else None
    return MeResponse(
        **UserResponse.model_validate(user).model_dump(),
        business=logo_service.business_summary(business) if business else None,
    )

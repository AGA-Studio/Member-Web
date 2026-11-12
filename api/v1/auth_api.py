"""Router for /api/v1/auth: login, logout and current session."""

from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from api.v1.dependencies import (
    CurrentUser,
    SessionDep,
    ensure_user_can_access,
    get_request_token,
)
from core.config import settings
from core.security import create_access_token, decode_access_token, verify_password
from models.user_model import User
from schemas.token_schema import Token
from schemas.user_schema import UserResponse
from services.auth_service import revoke_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(
    response: Response,
    session: SessionDep,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """Log in with email (`username` field) and password.

    Sets the JWT in an httpOnly cookie for the frontend and also returns it in the
    body for Swagger and the cashier reader.
    """
    user = session.exec(select(User).where(User.email == form.username.lower())).first()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
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


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> User:
    return user

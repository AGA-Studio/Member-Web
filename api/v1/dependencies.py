"""Shared router dependencies: DB session, current user and permissions."""

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from core.config import settings
from core.security import decode_access_token
from db.database import get_session
from models.user_model import Role, User
from schemas.token_schema import TokenData

# The frontend sends the token in the httpOnly cookie; the Bearer header is kept for
# Swagger (/docs) and tests. auto_error=False so the cookie can be checked afterwards.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

SessionDep = Annotated[Session, Depends(get_session)]

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated or session expired",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_token_data(
    request: Request, bearer: Annotated[str | None, Depends(oauth2_scheme)]
) -> TokenData:
    token = request.cookies.get(settings.cookie_name) or bearer
    if not token:
        raise _credentials_error
    try:
        payload = decode_access_token(token)
        return TokenData(
            user_id=int(payload["sub"]),
            role=payload["role"],
            business_id=payload.get("business_id"),
        )
    except jwt.InvalidTokenError, KeyError, ValueError:
        raise _credentials_error from None


def get_current_user(
    session: SessionDep, token_data: Annotated[TokenData, Depends(get_token_data)]
) -> User:
    user = session.get(User, token_data.user_id)
    if user is None:
        raise _credentials_error
    return user


def get_current_active_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_active_user)]


def require_roles(*roles: Role):
    """Usage: `Depends(require_roles(Role.ADMIN))`."""

    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return user

    return checker


def get_business_id(user: CurrentUser) -> int:
    """The authenticated user's business. Every business-data query filters by it."""
    if user.business_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This user does not belong to a business"
        )
    return user.business_id


BusinessId = Annotated[int, Depends(get_business_id)]

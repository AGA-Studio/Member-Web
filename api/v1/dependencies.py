"""Shared router dependencies: DB session, current user and permissions."""

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from core.config import settings
from core.errors import ApiError, ErrorCode
from core.security import decode_access_token
from db.database import get_session
from models.business_model import Business, BusinessStatus
from models.user_model import Role, User
from schemas.token_schema import TokenData
from services.auth_service import is_token_revoked

# The frontend sends the token in the httpOnly cookie; the Bearer header is kept for
# Swagger (/docs) and tests. auto_error=False so the cookie can be checked afterwards.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

SessionDep = Annotated[Session, Depends(get_session)]

_credentials_error = ApiError(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated or session expired",
    code=ErrorCode.NOT_AUTHENTICATED,
    headers={"WWW-Authenticate": "Bearer"},
)


def get_request_token(
    request: Request, bearer: Annotated[str | None, Depends(oauth2_scheme)]
) -> str | None:
    """Raw token from the httpOnly cookie (frontend) or the Bearer header."""
    return request.cookies.get(settings.cookie_name) or bearer


def get_token_data(
    session: SessionDep, token: Annotated[str | None, Depends(get_request_token)]
) -> TokenData:
    if not token:
        raise _credentials_error
    try:
        payload = decode_access_token(token)
        token_data = TokenData(
            user_id=int(payload["sub"]),
            role=payload["role"],
            business_id=payload.get("business_id"),
            jti=payload["jti"],
        )
    except jwt.InvalidTokenError, KeyError, ValueError:
        raise _credentials_error from None
    # H2: a token used to log out is dead even though its signature is still valid.
    if is_token_revoked(session, token_data.jti):
        raise _credentials_error
    return token_data


def get_current_user(
    session: SessionDep, token_data: Annotated[TokenData, Depends(get_token_data)]
) -> User:
    user = session.get(User, token_data.user_id)
    if user is None:
        raise _credentials_error
    return user


def ensure_user_can_access(session: Session, user: User) -> None:
    """Shared by login and every authenticated request.

    Blocks inactive users and users whose business is suspended. The platform
    owner has no business, so only `is_active` applies to them.
    """
    if not user.is_active:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
            code=ErrorCode.USER_INACTIVE,
        )
    if user.business_id is not None:
        business = session.get(Business, user.business_id)
        if business is None or business.status == BusinessStatus.SUSPENDED:
            raise ApiError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Business suspended",
                code=ErrorCode.BUSINESS_SUSPENDED,
            )


def get_current_active_user(
    session: SessionDep, user: Annotated[User, Depends(get_current_user)]
) -> User:
    ensure_user_can_access(session, user)
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

"""Router for /api/v1/user: admin and employee accounts of a business.

Every operation is scoped to the token's business (`BusinessId`).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from api.v1.dependencies import BusinessId, CurrentUser, SessionDep, require_roles
from core.errors import ApiError, ErrorCode
from core.security import hash_password
from models.user_model import Role, User
from schemas.user_schema import UserCreate, UserResponse, UserUpdate

router = APIRouter(
    prefix="/user",
    tags=["user"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
)


def _get_business_user(session: SessionDep, user_id: int, business_id: int) -> User:
    user = session.get(User, user_id)
    # A user from another business returns 404, same as if it didn't exist.
    if user is None or user.business_id != business_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


_email_in_use = ApiError(
    status_code=status.HTTP_409_CONFLICT,
    detail="Email already in use",
    code=ErrorCode.EMAIL_TAKEN,
)


def _ensure_email_available(session: SessionDep, email: str) -> None:
    if session.exec(select(User).where(User.email == email)).first():
        raise _email_in_use


def _save(session: SessionDep, user: User) -> User:
    """Commit the user; a unique-email race that slips past the check above is a 409.

    `_ensure_email_available` answers fast in the normal case, but two requests can
    both pass it before either commits. The unique index on `users.email` stops the
    second one; without this it would surface as a 500.
    """
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise _email_in_use from None
    session.refresh(user)
    return user


@router.get("/list", response_model=list[UserResponse])
def list_users(session: SessionDep, business_id: BusinessId) -> list[User]:
    return list(session.exec(select(User).where(User.business_id == business_id)).all())


@router.post("/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, session: SessionDep, business_id: BusinessId) -> User:
    if data.role == Role.PLATFORM:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role not allowed")
    email = data.email.lower()
    _ensure_email_available(session, email)
    user = User(
        business_id=business_id,
        name=data.name,
        email=email,
        hashed_password=hash_password(data.password),
        role=data.role,
    )
    return _save(session, user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, session: SessionDep, business_id: BusinessId) -> User:
    return _get_business_user(session, user_id, business_id)


@router.patch("/{user_id}/update", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    session: SessionDep,
    business_id: BusinessId,
    current_user: CurrentUser,
) -> User:
    user = _get_business_user(session, user_id, business_id)
    changes = data.model_dump(exclude_unset=True)
    # An admin locking themselves out could leave the business without an admin.
    if user.id == current_user.id and changes.get("is_active") is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )
    if "email" in changes:
        changes["email"] = changes["email"].lower()
        if changes["email"] != user.email:
            _ensure_email_available(session, changes["email"])
    if "password" in changes:
        user.hashed_password = hash_password(changes.pop("password"))
    for field, value in changes.items():
        setattr(user, field, value)
    return _save(session, user)

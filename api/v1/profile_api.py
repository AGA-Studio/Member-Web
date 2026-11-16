"""Router for /api/v1/user/photo: the session user's own profile photo.

Any active user (admin, employee or platform owner) changes only their own
photo. It lives apart from user_api because /user is admin-only, and there is
no user id in the path, so nobody can reach someone else's photo.
"""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from api.v1.dependencies import CurrentUser, SessionDep
from api.v1.uploads import image_errors, read_image
from schemas.user_schema import UserResponse
from services import profile_service

router = APIRouter(prefix="/user/photo", tags=["user"])


@router.post("/update", response_model=UserResponse)
def update_photo(
    session: SessionDep,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, up to 2 MB")],
) -> UserResponse:
    """Upload or replace your profile photo (512 px WebP, no metadata)."""
    data = read_image(file)
    with image_errors():
        profile_service.set_photo(session, user, data)
    return UserResponse.model_validate(user)


@router.post("/delete", response_model=UserResponse)
def delete_photo(session: SessionDep, user: CurrentUser) -> UserResponse:
    """Remove your profile photo. Without one it changes nothing."""
    profile_service.remove_photo(session, user)
    return UserResponse.model_validate(user)

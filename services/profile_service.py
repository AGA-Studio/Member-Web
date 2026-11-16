"""Profile photo of the session user (admin, employee or platform owner).

Each user changes only their own photo: the routes take no user id at all.
Keys live under the user's business, like every other object; the platform
owner has no business, so theirs go under `platform/`.
"""

from uuid import uuid4

from sqlmodel import Session

from models.user_model import User
from services import upload_service


def photo_key(user: User) -> str:
    owner = f"businesses/{user.business_id}" if user.business_id is not None else "platform"
    return f"{owner}/users/{user.id}/photo/{uuid4().hex}.webp"


def set_photo(session: Session, user: User, data: bytes) -> User:
    """Raises image_service.ImageRejected or storage_service.StorageUnavailable."""
    upload_service.replace_image(session, user, "photo_url", photo_key(user), data)
    return user


def remove_photo(session: Session, user: User) -> User:
    upload_service.remove_image(session, user, "photo_url")
    return user

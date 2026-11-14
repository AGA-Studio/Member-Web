"""Router for /api/v1/logo: the logo of the token's business.

Admin only. The business always comes from the token (`BusinessId`): there is
no way to name another business, so there is nothing of another business to
reach. Reading the logo is part of `/auth/me` (`business.logo_url`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from api.v1.dependencies import BusinessId, SessionDep, require_roles
from core.errors import ApiError, ErrorCode
from models.business_model import Business
from models.user_model import Role
from schemas.business_schema import BusinessSummaryResponse
from services import image_service, logo_service, storage_service

router = APIRouter(
    prefix="/logo",
    tags=["logo"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
)


def _business(session: SessionDep, business_id: int) -> Business:
    # The token's business always exists: users are tied to it by a foreign key.
    return session.get(Business, business_id)


@router.post("/update", response_model=BusinessSummaryResponse)
def update_logo(
    session: SessionDep,
    business_id: BusinessId,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, up to 2 MB")],
) -> BusinessSummaryResponse:
    """Upload or replace the logo. Stored as a 512 px WebP without metadata."""
    # Read one byte past the limit: enough to know it is too big, never more.
    data = file.file.read(image_service.MAX_UPLOAD_BYTES + 1)
    if len(data) > image_service.MAX_UPLOAD_BYTES:
        raise ApiError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "The image is larger than 2 MB",
            ErrorCode.IMAGE_TOO_LARGE,
        )
    try:
        business = logo_service.set_logo(session, _business(session, business_id), data)
    except image_service.ImageRejected as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error), ErrorCode.IMAGE_INVALID
        ) from None
    except storage_service.StorageUnavailable:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Image storage is not available",
            ErrorCode.STORAGE_UNAVAILABLE,
        ) from None
    return logo_service.business_summary(business)


@router.post("/delete", response_model=BusinessSummaryResponse)
def delete_logo(session: SessionDep, business_id: BusinessId) -> BusinessSummaryResponse:
    """Remove the logo. Repeating it changes nothing."""
    business = logo_service.remove_logo(session, _business(session, business_id))
    return logo_service.business_summary(business)

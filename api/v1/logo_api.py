"""Router for /api/v1/logo: the logo of the token's business.

Admin only. The business always comes from the token (`BusinessId`): there is
no way to name another business, so there is nothing of another business to
reach. Reading the logo is part of `/auth/me` (`business.logo_url`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from api.v1.dependencies import BusinessId, SessionDep, require_permission
from api.v1.uploads import image_errors, read_image
from core.permissions import Permission
from models.business_model import Business
from schemas.business_schema import BusinessSummaryResponse
from services import logo_service

router = APIRouter(
    prefix="/logo",
    tags=["logo"],
    dependencies=[Depends(require_permission(Permission.BUSINESS_MANAGE))],
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
    data = read_image(file)
    with image_errors():
        business = logo_service.set_logo(session, _business(session, business_id), data)
    return logo_service.business_summary(business)


@router.post("/delete", response_model=BusinessSummaryResponse)
def delete_logo(session: SessionDep, business_id: BusinessId) -> BusinessSummaryResponse:
    """Remove the logo. Repeating it changes nothing."""
    business = logo_service.remove_logo(session, _business(session, business_id))
    return logo_service.business_summary(business)

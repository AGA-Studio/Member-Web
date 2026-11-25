"""Router for /api/v1/business: the settings of the token's business (screen 13).

Admin only. The business always comes from the token (`BusinessId`), so there is
no way to reach another business. Reading the settings is part of `/auth/me`
(`business`); the logo has its own router (`/logo`).
"""

from fastapi import APIRouter, Depends

from api.v1.dependencies import BusinessId, SessionDep, require_permission
from core.permissions import Permission
from schemas.business_schema import BusinessSummaryResponse, BusinessUpdate
from services import business_service, logo_service

router = APIRouter(
    prefix="/business",
    tags=["business"],
    dependencies=[Depends(require_permission(Permission.BUSINESS_MANAGE))],
)


@router.patch("/update", response_model=BusinessSummaryResponse)
def update_business(
    session: SessionDep, business_id: BusinessId, data: BusinessUpdate
) -> BusinessSummaryResponse:
    """Change the name and/or `validity_months`. Returns what `/auth/me` shows."""
    business = business_service.update_business(session, business_id, data)
    return logo_service.business_summary(business)

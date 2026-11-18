"""Router for /api/v1/platform: the platform owner's view of the businesses.

Only the `platform` role. It belongs to no business, so nothing here filters by one:
it sees every business, but only its status and usage, and only changes its status.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from api.v1.dependencies import SessionDep, require_roles
from models.business_model import BusinessStatus
from models.user_model import Role
from schemas.pagination_schema import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageResponse
from schemas.platform_schema import (
    PlatformBusinessDetailResponse,
    PlatformBusinessResponse,
    PlatformBusinessUpdate,
    PlatformSummaryResponse,
)
from services import platform_service

router = APIRouter(
    prefix="/platform",
    tags=["platform"],
    dependencies=[Depends(require_roles(Role.PLATFORM))],
)


@router.get("/business/list", response_model=PageResponse[PlatformBusinessResponse])
def list_businesses(
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status_filter: Annotated[BusinessStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageResponse[PlatformBusinessResponse]:
    """Status and usage of every business, by name. Never customer data."""
    return platform_service.list_businesses(
        session, q=q, status_filter=status_filter, page=page, page_size=page_size
    )


# Declared before `/business/{business_id}` so "summary" is not read as an id.
@router.get("/business/summary", response_model=PlatformSummaryResponse)
def summary(session: SessionDep) -> PlatformSummaryResponse:
    """Businesses by status and total usage, for the platform dashboard. Only counts."""
    return platform_service.summary(session)


@router.get("/business/{business_id}", response_model=PlatformBusinessDetailResponse)
def get_business(session: SessionDep, business_id: int) -> PlatformBusinessDetailResponse:
    """One business: status, configuration and usage. 404 `business_not_found`."""
    return platform_service.get_business(session, business_id)


@router.patch("/business/{business_id}/update", response_model=PlatformBusinessDetailResponse)
def update_business(
    session: SessionDep, business_id: int, data: PlatformBusinessUpdate
) -> PlatformBusinessDetailResponse:
    """Suspends (`suspended`) or reactivates (`active`) a business."""
    return platform_service.update_business(session, business_id, data)

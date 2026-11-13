"""Router for /api/v1/platform: the platform owner's read-only view of the businesses.

Only the `platform` role. It belongs to no business, so nothing here filters by one:
it sees every business, but only its status and usage.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from api.v1.dependencies import SessionDep, require_roles
from models.business_model import BusinessStatus
from models.user_model import Role
from schemas.pagination_schema import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageResponse
from schemas.platform_schema import PlatformBusinessResponse
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

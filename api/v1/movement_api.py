"""Router for /api/v1/movement: purchase history of the business (admin only).

The business comes from the token. Both routes take the same filters.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from api.v1.dependencies import BusinessId, SessionDep, require_roles
from models.user_model import Role
from schemas.movement_schema import MovementPageResponse
from schemas.pagination_schema import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from services import movement_service

router = APIRouter(
    prefix="/movement",
    tags=["movement"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
)

SearchText = Annotated[str | None, Query(max_length=120, description="Customer name or code")]
DateFrom = Annotated[datetime | None, Query(alias="from", description="Inclusive; UTC if naive")]
DateTo = Annotated[datetime | None, Query(alias="to", description="Inclusive; UTC if naive")]


@router.get("/list", response_model=MovementPageResponse)
def list_movements(
    session: SessionDep,
    business_id: BusinessId,
    q: SearchText = None,
    customer_id: int | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> MovementPageResponse:
    """Newest first, with `summary` of the whole filtered set."""
    return movement_service.list_movements(
        session,
        business_id,
        q=q,
        customer_id=customer_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "CSV file"}},
)
def export_movements(
    session: SessionDep,
    business_id: BusinessId,
    q: SearchText = None,
    customer_id: int | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Response:
    """Same filters as `list`, without pagination, as a CSV download."""
    content = movement_service.export_csv(
        session,
        business_id,
        q=q,
        customer_id=customer_id,
        date_from=date_from,
        date_to=date_to,
    )
    filename = f"movimientos-{datetime.now(UTC):%Y%m%d}.csv"
    # The BOM lets Excel open the accents correctly.
    return Response(
        content="﻿" + content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

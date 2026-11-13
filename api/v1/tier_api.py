"""Router for /api/v1/tier: membership levels of a business.

Every operation is scoped to the token's business (`BusinessId`). The cashier
can read the tiers (the checkout shows their benefits); only the admin edits them.
"""

from fastapi import APIRouter, Depends

from api.v1.dependencies import BusinessId, SessionDep, require_roles
from models.user_model import Role
from schemas.tier_schema import TierResponse, TierUpdate
from services import tier_service

router = APIRouter(prefix="/tier", tags=["tier"])


@router.get(
    "/list",
    response_model=list[TierResponse],
    dependencies=[Depends(require_roles(Role.ADMIN, Role.EMPLOYEE))],
)
def list_tiers(session: SessionDep, business_id: BusinessId) -> list[TierResponse]:
    """All the business's tiers, without pagination, by `min_points` ascending."""
    return tier_service.list_tiers(session, business_id)


@router.patch(
    "/{tier_id}/update",
    response_model=TierResponse,
    dependencies=[Depends(require_roles(Role.ADMIN))],
)
def update_tier(
    tier_id: int, data: TierUpdate, session: SessionDep, business_id: BusinessId
) -> TierResponse:
    """Edit a tier. Applies to new purchases only; past ones are not recalculated."""
    return tier_service.update_tier(session, business_id, tier_id, data)

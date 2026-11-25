"""Router for /api/v1/plan: the plan catalog and the session business's plan (issue #70).

`/list` has no session: the sign-up form and the landing show it before anyone
logs in. It holds prices and limits, never data of a business. Hidden plans
(assigned by the platform owner by hand) are left out.

`/summary` is the admin's view of their own business's plan and usage.
"""

from fastapi import APIRouter, Depends

from api.v1.dependencies import BusinessId, SessionDep, require_permission
from core.permissions import Permission
from schemas.plan_schema import PlanResponse, PlanSummaryResponse
from services import plan_service

router = APIRouter(prefix="/plan", tags=["plan"])


@router.get("/list", response_model=list[PlanResponse])
def list_plans(session: SessionDep) -> list[PlanResponse]:
    """Plans a business can pick, cheapest first."""
    return [PlanResponse.model_validate(plan) for plan in plan_service.public_plans(session)]


@router.get(
    "/summary",
    response_model=PlanSummaryResponse,
    dependencies=[Depends(require_permission(Permission.BUSINESS_MANAGE))],
)
def plan_summary(session: SessionDep, business_id: BusinessId) -> PlanSummaryResponse:
    """Effective plan of the session's business, its trial and its usage against the limits."""
    return plan_service.summary(session, business_id)

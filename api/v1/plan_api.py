"""Router for /api/v1/plan: the plan catalog and the session business's plan (issue #70).

`/list` has no session: the sign-up form and the landing show it before anyone
logs in. It holds prices and limits, never data of a business. Hidden plans
(assigned by the platform owner by hand) are left out.

`/summary` is the admin's view of their own business's plan and usage, and
`/update` lets the admin change it (behind `PLAN_SELF_SERVICE_ENABLED`).
"""

from fastapi import APIRouter, Depends

from api.v1.dependencies import BusinessId, SessionDep, require_permission
from core.permissions import Permission
from schemas.plan_schema import PlanResponse, PlanSummaryResponse, PlanUpdate
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


def ensure_plan_change_open(session: SessionDep, business_id: BusinessId) -> None:
    """A dependency, so a closed change answers 403 before the body is validated."""
    plan_service.ensure_can_change_plan(session, business_id)


@router.patch(
    "/update",
    response_model=PlanSummaryResponse,
    dependencies=[
        Depends(require_permission(Permission.BUSINESS_MANAGE)),
        Depends(ensure_plan_change_open),
    ],
)
def update_plan(
    data: PlanUpdate, session: SessionDep, business_id: BusinessId
) -> PlanSummaryResponse:
    """The admin changes their business's plan. The payment is simulated in the frontend."""
    return plan_service.change_by_business(session, business_id, data.plan_id)

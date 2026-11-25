"""Router for /api/v1/plan: the public catalog of plans (issue #70).

No session: the sign-up form and the landing show it before anyone logs in.
It holds prices and limits, never data of a business. Hidden plans (assigned by
the platform owner by hand) are left out.
"""

from fastapi import APIRouter

from api.v1.dependencies import SessionDep
from schemas.plan_schema import PlanResponse
from services import plan_service

router = APIRouter(prefix="/plan", tags=["plan"])


@router.get("/list", response_model=list[PlanResponse])
def list_plans(session: SessionDep) -> list[PlanResponse]:
    """Plans a business can pick, cheapest first."""
    return [PlanResponse.model_validate(plan) for plan in plan_service.public_plans(session)]

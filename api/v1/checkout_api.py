"""Router for /api/v1/checkout: charge at the counter and read the receipt.

Admins and cashiers can charge. The cashier who charges comes from the token.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status

from api.v1.dependencies import BusinessId, SessionDep, require_roles
from models.user_model import Role, User
from schemas.checkout_schema import CheckoutCreate, CheckoutPreviewResponse, ReceiptResponse
from services import checkout_service

router = APIRouter(prefix="/checkout", tags=["checkout"])

CounterUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.EMPLOYEE))]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=64)]


@router.post("/preview", response_model=CheckoutPreviewResponse)
def preview(
    data: CheckoutCreate, session: SessionDep, business_id: BusinessId, _: CounterUser
) -> CheckoutPreviewResponse:
    """Same body as `create`; computes the numbers and saves nothing."""
    return checkout_service.preview(session, business_id, data)


@router.post("/create", response_model=ReceiptResponse, status_code=status.HTTP_201_CREATED)
def create(
    data: CheckoutCreate,
    session: SessionDep,
    business_id: BusinessId,
    cashier: CounterUser,
    response: Response,
    idempotency_key: IdempotencyKey = None,
) -> ReceiptResponse:
    """Register the purchase. Retrying with the same `Idempotency-Key` does not charge twice."""
    receipt, replayed = checkout_service.create(
        session, business_id, cashier, data, idempotency_key
    )
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return receipt


@router.get("/{checkout_id}", response_model=ReceiptResponse)
def get_receipt(
    checkout_id: int, session: SessionDep, business_id: BusinessId, user: CounterUser
) -> ReceiptResponse:
    """Receipt by id. A cashier only sees the ones they registered."""
    return checkout_service.get_receipt(session, business_id, user, checkout_id)

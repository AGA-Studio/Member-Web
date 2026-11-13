"""Router for /api/v1/customer: customers of a business and their card.

Every operation is scoped to the token's business (`BusinessId`). The cashier
can only look a card up at the counter; everything else is for the admin.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from api.v1.dependencies import BusinessId, SessionDep, require_roles
from models.user_model import Role
from schemas.card_schema import CardEmailSentResponse, CardLinkResponse, CustomerCreatedResponse
from schemas.customer_schema import (
    CustomerCreate,
    CustomerResponse,
    CustomerStatusFilter,
    CustomerSummaryResponse,
    CustomerUpdate,
)
from schemas.pagination_schema import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageResponse
from services import card_service, customer_service

router = APIRouter(prefix="/customer", tags=["customer"])

admin_only = [Depends(require_roles(Role.ADMIN))]


@router.get("/list", response_model=PageResponse[CustomerResponse], dependencies=admin_only)
def list_customers(
    session: SessionDep,
    business_id: BusinessId,
    q: Annotated[str | None, Query(max_length=120)] = None,
    level_id: int | None = None,
    status_filter: Annotated[CustomerStatusFilter | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageResponse[CustomerResponse]:
    """Paginated, by `full_name`. `q` searches name, email and code, ignoring case."""
    return customer_service.list_customers(
        session,
        business_id,
        q=q,
        level_id=level_id,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=CustomerSummaryResponse, dependencies=admin_only)
def summary(session: SessionDep, business_id: BusinessId) -> CustomerSummaryResponse:
    return customer_service.summary(session, business_id)


@router.get(
    "/lookup",
    response_model=CustomerResponse,
    dependencies=[Depends(require_roles(Role.ADMIN, Role.EMPLOYEE))],
)
def lookup(
    session: SessionDep,
    business_id: BusinessId,
    code: Annotated[str, Query(min_length=1, max_length=32)],
) -> CustomerResponse:
    """Card read at the counter (QR or typed code). Also answers for expired/cancelled."""
    return customer_service.lookup(session, business_id, code)


@router.post(
    "/create",
    response_model=CustomerCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=admin_only,
)
def create_customer(
    data: CustomerCreate, session: SessionDep, business_id: BusinessId
) -> CustomerCreatedResponse:
    """With `send_card_email` (default) it emails the card link; a failed email never fails it."""
    return card_service.create_customer(session, business_id, data)


@router.get("/{customer_id}", response_model=CustomerResponse, dependencies=admin_only)
def get_customer(
    customer_id: int, session: SessionDep, business_id: BusinessId
) -> CustomerResponse:
    return customer_service.get_customer(session, business_id, customer_id)


@router.patch("/{customer_id}/update", response_model=CustomerResponse, dependencies=admin_only)
def update_customer(
    customer_id: int, data: CustomerUpdate, session: SessionDep, business_id: BusinessId
) -> CustomerResponse:
    return customer_service.update_customer(session, business_id, customer_id, data)


@router.post("/{customer_id}/cancel", response_model=CustomerResponse, dependencies=admin_only)
def cancel_customer(
    customer_id: int, session: SessionDep, business_id: BusinessId
) -> CustomerResponse:
    """Irreversible: the card stays `cancelled`."""
    return customer_service.cancel_customer(session, business_id, customer_id)


@router.post("/{customer_id}/card-link", response_model=CardLinkResponse, dependencies=admin_only)
def create_card_link(
    customer_id: int, session: SessionDep, business_id: BusinessId
) -> CardLinkResponse:
    """New link to the digital card ("Copiar enlace"). The previous link stops working."""
    return card_service.create_link(session, business_id, customer_id)


@router.post(
    "/{customer_id}/card-link/send", response_model=CardEmailSentResponse, dependencies=admin_only
)
def send_card_link(
    customer_id: int, session: SessionDep, business_id: BusinessId
) -> CardEmailSentResponse:
    """Email the customer a new card link. One per minute and five per hour."""
    return card_service.send_link(session, business_id, customer_id)

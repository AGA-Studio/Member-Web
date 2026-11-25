"""Router for /api/v1/customer: customers of a business and their card.

Every operation is scoped to the token's business (`BusinessId`). The cashier
can only look a card up at the counter; managing customers needs
`Permission.CUSTOMERS_MANAGE` (admin and manager, `core/permissions.py`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from api.v1.dependencies import (
    BusinessId,
    SessionDep,
    require_permission,
    require_plan_feature,
)
from api.v1.uploads import image_errors, read_image
from core.permissions import Permission
from models.user_model import User
from schemas.card_schema import CardEmailSentResponse, CardLinkResponse, CustomerCreatedResponse
from schemas.customer_schema import (
    CustomerCreate,
    CustomerRenew,
    CustomerResponse,
    CustomerStatusFilter,
    CustomerSummaryResponse,
    CustomerUpdate,
)
from schemas.pagination_schema import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageResponse
from schemas.payment_schema import MembershipPaymentResponse
from services import card_service, customer_service, payment_service
from services.plan_service import Feature

router = APIRouter(prefix="/customer", tags=["customer"])

managers = [Depends(require_permission(Permission.CUSTOMERS_MANAGE))]
CustomerManager = Annotated[User, Depends(require_permission(Permission.CUSTOMERS_MANAGE))]


@router.get("/list", response_model=PageResponse[CustomerResponse], dependencies=managers)
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


@router.get("/summary", response_model=CustomerSummaryResponse, dependencies=managers)
def summary(session: SessionDep, business_id: BusinessId) -> CustomerSummaryResponse:
    return customer_service.summary(session, business_id)


@router.get(
    "/lookup",
    response_model=CustomerResponse,
    dependencies=[Depends(require_permission(Permission.CUSTOMERS_LOOKUP))],
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
)
def create_customer(
    data: CustomerCreate, session: SessionDep, business_id: BusinessId, staff: CustomerManager
) -> CustomerCreatedResponse:
    """Records the first payment. With `send_card_email` (default) it emails the card link."""
    return card_service.create_customer(session, business_id, data, staff.id)


@router.get("/{customer_id}", response_model=CustomerResponse, dependencies=managers)
def get_customer(
    customer_id: int, session: SessionDep, business_id: BusinessId
) -> CustomerResponse:
    return customer_service.get_customer(session, business_id, customer_id)


@router.patch("/{customer_id}/update", response_model=CustomerResponse, dependencies=managers)
def update_customer(
    customer_id: int, data: CustomerUpdate, session: SessionDep, business_id: BusinessId
) -> CustomerResponse:
    return customer_service.update_customer(session, business_id, customer_id, data)


@router.post("/{customer_id}/cancel", response_model=CustomerResponse, dependencies=managers)
def cancel_customer(
    customer_id: int, session: SessionDep, business_id: BusinessId
) -> CustomerResponse:
    """Irreversible: the card stays `cancelled` and its photo is deleted."""
    return customer_service.cancel_customer(session, business_id, customer_id)


@router.post(
    "/{customer_id}/photo/update",
    response_model=CustomerResponse,
    dependencies=[*managers, Depends(require_plan_feature(Feature.IMAGES))],
)
def update_customer_photo(
    customer_id: int,
    session: SessionDep,
    business_id: BusinessId,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, up to 2 MB")],
) -> CustomerResponse:
    """Upload or replace the customer's photo (512 px WebP, no metadata).

    Only to show the customer in the panel and at the counter: no biometric use.
    """
    data = read_image(file)
    with image_errors():
        return customer_service.set_photo(session, business_id, customer_id, data)


@router.post("/{customer_id}/photo/delete", response_model=CustomerResponse, dependencies=managers)
def delete_customer_photo(
    customer_id: int, session: SessionDep, business_id: BusinessId
) -> CustomerResponse:
    """Remove the photo. Without a photo it changes nothing."""
    return customer_service.remove_photo(session, business_id, customer_id)


@router.post("/{customer_id}/card-link", response_model=CardLinkResponse, dependencies=managers)
def create_card_link(
    customer_id: int, session: SessionDep, business_id: BusinessId
) -> CardLinkResponse:
    """New link to the digital card ("Copiar enlace"). The previous link stops working."""
    return card_service.create_link(session, business_id, customer_id)


@router.post(
    "/{customer_id}/card-link/send",
    response_model=CardEmailSentResponse,
    dependencies=managers,
)
def send_card_link(
    customer_id: int, session: SessionDep, business_id: BusinessId
) -> CardEmailSentResponse:
    """Email the customer a new card link. One per minute and five per hour."""
    return card_service.send_link(session, business_id, customer_id)


@router.post("/{customer_id}/renew", response_model=CustomerResponse)
def renew_customer(
    customer_id: int,
    data: CustomerRenew,
    session: SessionDep,
    business_id: BusinessId,
    staff: CustomerManager,
) -> CustomerResponse:
    """Extend the card and record its payment. A cancelled card is 409."""
    return customer_service.renew_customer(session, business_id, customer_id, data, staff.id)


@router.get(
    "/{customer_id}/payment/list",
    response_model=PageResponse[MembershipPaymentResponse],
    dependencies=managers,
)
def list_payments(
    customer_id: int,
    session: SessionDep,
    business_id: BusinessId,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageResponse[MembershipPaymentResponse]:
    """Membership payments of the customer, most recent first."""
    return payment_service.list_payments(
        session, business_id, customer_id, page=page, page_size=page_size
    )

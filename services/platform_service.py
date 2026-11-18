"""What the platform owner sees and does: the businesses of the SaaS (contract, section 7).

The platform has no `business_id`: it sees every business, but only its status and
usage. No customer, user or purchase data ever leaves here. The only thing it
changes is the status (suspend and reactivate).

Rules:
- Ordered by `name`, then `id`.
- `q` searches the business name, ignoring case.
- `customers_count` counts cards that are not cancelled, the same rule as
  `customers_count` of a tier.
- `users_count` counts the business's active users.
- Suspending cuts every session of the business on its next request: that rule
  lives in `ensure_user_can_access`, not here. Reactivating lets them log in again.
"""

import math

from fastapi import status
from sqlalchemy import ColumnElement, func
from sqlmodel import Session, select

from core.errors import ApiError, ErrorCode
from models.business_model import Business, BusinessStatus
from models.customer_model import Customer
from models.user_model import User
from schemas.pagination_schema import PageResponse
from schemas.platform_schema import (
    PlatformBusinessDetailResponse,
    PlatformBusinessResponse,
    PlatformBusinessUpdate,
)
from services import storage_service
from services.customer_service import as_utc


def _customer_counts(session: Session, business_ids: list[int]) -> dict[int, int]:
    if not business_ids:
        return {}
    query = (
        select(Customer.business_id, func.count())
        .where(Customer.business_id.in_(business_ids), Customer.cancelled_at.is_(None))  # type: ignore[union-attr]
        .group_by(Customer.business_id)
    )
    return dict(session.exec(query).all())


def _item(business: Business, customers_count: int) -> PlatformBusinessResponse:
    return PlatformBusinessResponse(
        id=business.id,
        name=business.name,
        logo_url=storage_service.public_url(business.logo_url),
        status=business.status,
        customers_count=customers_count,
        created_at=as_utc(business.created_at),
    )


def list_businesses(
    session: Session,
    *,
    q: str | None = None,
    status_filter: BusinessStatus | None = None,
    page: int = 1,
    page_size: int = 8,
) -> PageResponse[PlatformBusinessResponse]:
    conditions: list[ColumnElement[bool]] = []
    if q and q.strip():
        needle = q.strip().lower()
        conditions.append(func.lower(Business.name).contains(needle, autoescape=True))
    if status_filter is not None:
        conditions.append(Business.status == status_filter)

    total = session.exec(select(func.count()).select_from(Business).where(*conditions)).one()
    last_page = max(1, math.ceil(total / page_size))
    page = min(page, last_page)
    rows = session.exec(
        select(Business)
        .where(*conditions)
        .order_by(Business.name, Business.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    counts = _customer_counts(session, [business.id for business in rows])
    return PageResponse[PlatformBusinessResponse](
        items=[_item(business, counts.get(business.id, 0)) for business in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


_not_found = ApiError(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Business not found",
    code=ErrorCode.BUSINESS_NOT_FOUND,
)


def _get(session: Session, business_id: int) -> Business:
    business = session.get(Business, business_id)
    if business is None:
        raise _not_found
    return business


def _detail(session: Session, business: Business) -> PlatformBusinessDetailResponse:
    users_count = session.exec(
        select(func.count())
        .select_from(User)
        .where(User.business_id == business.id, User.is_active.is_(True))  # type: ignore[attr-defined]
    ).one()
    item = _item(business, _customer_counts(session, [business.id]).get(business.id, 0))
    return PlatformBusinessDetailResponse(
        **item.model_dump(),
        validity_months=business.validity_months,
        users_count=users_count,
    )


def get_business(session: Session, business_id: int) -> PlatformBusinessDetailResponse:
    return _detail(session, _get(session, business_id))


def update_business(
    session: Session, business_id: int, data: PlatformBusinessUpdate
) -> PlatformBusinessDetailResponse:
    """Suspends or reactivates. Setting the status it already has is a no-op, not an error."""
    business = _get(session, business_id)
    if business.status != data.status:
        business.status = data.status
        session.add(business)
        session.commit()
        session.refresh(business)
    return _detail(session, business)

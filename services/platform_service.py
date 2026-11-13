"""What the platform owner sees: the businesses of the SaaS (contract, section 7).

Read only. The platform has no `business_id`: it sees every business, but only
its status and usage. No customer, user or purchase data ever leaves here.

Rules:
- Ordered by `name`, then `id`.
- `q` searches the business name, ignoring case.
- `customers_count` counts cards that are not cancelled, the same rule as
  `customers_count` of a tier.
"""

import math

from sqlalchemy import ColumnElement, func
from sqlmodel import Session, select

from models.business_model import Business, BusinessStatus
from models.customer_model import Customer
from schemas.pagination_schema import PageResponse
from schemas.platform_schema import PlatformBusinessResponse
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
        items=[
            PlatformBusinessResponse(
                id=business.id,
                name=business.name,
                status=business.status,
                customers_count=counts.get(business.id, 0),
                created_at=as_utc(business.created_at),
            )
            for business in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )

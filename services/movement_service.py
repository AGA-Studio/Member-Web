"""Movement history of a business: list with totals and CSV export (contract, section 6).

Every function receives the `business_id` from the token and only reads rows of
that business. A `customer_id` of another business is not an error: it simply
matches nothing.

Rules:
- Newest first (`created_at`, then `id`).
- `q` searches the customer's name or card code, ignoring case.
- `date_from` and `date_to` are inclusive. A date without time zone is UTC.
- `summary` adds up the whole filtered set, not just the page.
- The CSV amounts are pesos with two decimals. A cell that starts with `=`,
  `+`, `-` or `@` gets a leading `'` so a spreadsheet does not run it as a
  formula.
"""

import csv
import io
import math
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, or_
from sqlmodel import Session, select

from models.customer_model import Customer
from models.purchase_model import Purchase
from models.user_model import User
from schemas.checkout_schema import CustomerRefResponse
from schemas.movement_schema import (
    MovementPageResponse,
    MovementResponse,
    MovementSummaryResponse,
)
from services.customer_service import as_utc

CSV_HEADER = [
    "Fecha",
    "Cajero",
    "Cliente",
    "Código",
    "Concepto",
    "Monto",
    "Descuento",
    "Total",
    "Puntos",
    "Cashback ganado",
    "Cashback usado",
]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _conditions(
    business_id: int,
    *,
    q: str | None,
    customer_id: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        Purchase.business_id == business_id,
        Customer.business_id == business_id,
    ]
    if q and q.strip():
        needle = q.strip().lower()
        conditions.append(
            or_(
                func.lower(Customer.full_name).contains(needle, autoescape=True),
                func.lower(Customer.code).contains(needle, autoescape=True),
            )
        )
    if customer_id is not None:
        conditions.append(Purchase.customer_id == customer_id)
    if date_from is not None:
        conditions.append(Purchase.created_at >= _utc(date_from))
    if date_to is not None:
        conditions.append(Purchase.created_at <= _utc(date_to))
    return conditions


def _rows(conditions: list[ColumnElement[bool]]):
    return (
        select(Purchase, Customer, User)
        .join(Customer, Customer.id == Purchase.customer_id)
        .join(User, User.id == Purchase.cashier_id)
        .where(*conditions)
        .order_by(Purchase.created_at.desc(), Purchase.id.desc())
    )


def to_movement(purchase: Purchase, customer: Customer, cashier: User) -> MovementResponse:
    return MovementResponse(
        id=purchase.id,
        created_at=as_utc(purchase.created_at),
        customer=CustomerRefResponse(
            id=customer.id, full_name=customer.full_name, code=customer.code
        ),
        cashier_name=cashier.name,
        card_status=purchase.card_status,
        concept=purchase.concept,
        amount_cents=purchase.amount_cents,
        discount_percent=purchase.discount_percent,
        discount_cents=purchase.discount_cents,
        cashback_used_cents=purchase.cashback_used_cents,
        total_cents=purchase.total_cents,
        points_delta=purchase.points_earned,
        cashback_earned_cents=purchase.cashback_earned_cents,
    )


def _summary(session: Session, conditions: list[ColumnElement[bool]]) -> MovementSummaryResponse:
    count, collected, discount, cashback_used = session.exec(
        select(
            func.count(Purchase.id),
            func.coalesce(func.sum(Purchase.total_cents), 0),
            func.coalesce(func.sum(Purchase.discount_cents), 0),
            func.coalesce(func.sum(Purchase.cashback_used_cents), 0),
        )
        .select_from(Purchase)
        .join(Customer, Customer.id == Purchase.customer_id)
        .where(*conditions)
    ).one()
    return MovementSummaryResponse(
        count=count,
        collected_cents=int(collected),
        discount_cents=int(discount),
        cashback_used_cents=int(cashback_used),
    )


def list_movements(
    session: Session,
    business_id: int,
    *,
    q: str | None = None,
    customer_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 8,
) -> MovementPageResponse:
    conditions = _conditions(
        business_id, q=q, customer_id=customer_id, date_from=date_from, date_to=date_to
    )
    summary = _summary(session, conditions)
    last_page = max(1, math.ceil(summary.count / page_size))
    page = min(page, last_page)
    rows = session.exec(_rows(conditions).offset((page - 1) * page_size).limit(page_size)).all()
    return MovementPageResponse(
        items=[to_movement(*row) for row in rows],
        total=summary.count,
        page=page,
        page_size=page_size,
        summary=summary,
    )


# --- CSV ----------------------------------------------------------------------


def pesos(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    return f"{sign}{whole}.{rest:02d}"


def safe_cell(value: str | None) -> str:
    """Text as typed, unless a spreadsheet would read it as a formula."""
    if not value:
        return ""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def export_csv(
    session: Session,
    business_id: int,
    *,
    q: str | None = None,
    customer_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> str:
    """Every filtered movement, newest first, without pagination."""
    conditions = _conditions(
        business_id, q=q, customer_id=customer_id, date_from=date_from, date_to=date_to
    )
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for purchase, customer, cashier in session.exec(_rows(conditions)):
        writer.writerow(
            [
                as_utc(purchase.created_at).isoformat().replace("+00:00", "Z"),
                safe_cell(cashier.name),
                safe_cell(customer.full_name),
                customer.code,
                safe_cell(purchase.concept),
                pesos(purchase.amount_cents),
                pesos(purchase.discount_cents),
                pesos(purchase.total_cents),
                purchase.points_earned,
                pesos(purchase.cashback_earned_cents),
                pesos(purchase.cashback_used_cents),
            ]
        )
    return out.getvalue()

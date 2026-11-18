"""Settings of the token's business: name, validity and color (screen 13).

Rules:
- The business always comes from the token; there is no way to name another one.
- Only the fields sent change; `null` or a missing field keeps the current value.
  Except `primary_color`, which is optional: `null` removes it (Member+ blue).
- `validity_months` is read when a card is created or renewed
  (`customer_service`), so changing it never moves an issued `valid_until`.
- The logo has its own routes (`/logo/update` and `/logo/delete`).
"""

from sqlmodel import Session

from models.business_model import Business
from schemas.business_schema import BusinessUpdate


def update_business(session: Session, business_id: int, data: BusinessUpdate) -> Business:
    # The token's business always exists: users are tied to it by a foreign key.
    business = session.get(Business, business_id)
    changes = data.model_dump(exclude_none=True)
    # The color is optional: an explicit null removes it (back to Member+ blue).
    if "primary_color" in data.model_fields_set:
        changes["primary_color"] = data.primary_color
    if changes:
        for field, value in changes.items():
            setattr(business, field, value)
        session.add(business)
        session.commit()
        session.refresh(business)
    return business

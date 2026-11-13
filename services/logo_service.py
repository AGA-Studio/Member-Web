"""Business logo: upload, replace, remove, and how it is shown.

`businesses.logo_url` holds either an external URL (kept as is) or a storage
key under `businesses/<business_id>/logo/`. The key, not a URL, goes to the
database, so changing provider or URL expiry needs no data migration.
"""

from uuid import uuid4

from sqlmodel import Session

from models.business_model import Business
from schemas.business_schema import BusinessSummaryResponse
from services import image_service, storage_service


def logo_key(business_id: int) -> str:
    # A fresh name per upload: browsers and CDNs never serve a stale cached logo.
    return f"businesses/{business_id}/logo/{uuid4().hex}.webp"


def business_summary(business: Business) -> BusinessSummaryResponse:
    """The business as the frontend sees it, with a usable logo URL."""
    summary = BusinessSummaryResponse.model_validate(business)
    return summary.model_copy(update={"logo_url": storage_service.public_url(business.logo_url)})


def set_logo(session: Session, business: Business, data: bytes) -> Business:
    """Store the processed image and point the business at it.

    Raises image_service.ImageRejected or storage_service.StorageUnavailable.
    """
    webp = image_service.to_webp(data)
    key = logo_key(business.id)
    storage_service.put_object(key, webp, image_service.CONTENT_TYPE)

    previous = business.logo_url
    business.logo_url = key
    session.add(business)
    session.commit()
    session.refresh(business)

    # Only after the commit: if it had failed, the old logo must still exist.
    if storage_service.is_storage_key(previous):
        storage_service.delete_object(previous)
    return business


def remove_logo(session: Session, business: Business) -> Business:
    previous = business.logo_url
    business.logo_url = None
    session.add(business)
    session.commit()
    session.refresh(business)
    if storage_service.is_storage_key(previous):
        storage_service.delete_object(previous)
    return business

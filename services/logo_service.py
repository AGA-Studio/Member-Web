"""Business logo: upload, replace, remove, and how it is shown.

`businesses.logo_url` holds either an external URL (kept as is) or a storage
key under `businesses/<business_id>/logo/`. The key, not a URL, goes to the
database, so changing provider or URL expiry needs no data migration.
"""

from uuid import uuid4

from sqlmodel import Session

from models.business_model import Business
from schemas.business_schema import BusinessSummaryResponse
from services import storage_service, upload_service


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
    upload_service.replace_image(session, business, "logo_url", logo_key(business.id), data)
    return business


def remove_logo(session: Session, business: Business) -> Business:
    upload_service.remove_image(session, business, "logo_url")
    return business

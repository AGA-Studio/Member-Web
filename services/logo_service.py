"""Business logo: upload, replace, remove, and how it is shown.

`businesses.logo_url` holds either an external URL (kept as is) or a storage
key under `businesses/<business_id>/logo/`. The key, not a URL, goes to the
database, so changing provider or URL expiry needs no data migration.

`pass_logo_url` is the exception to "keys become signed URLs": the Google Wallet
pass and the card email need a URL that never expires, so the API serves the
logo itself as a square PNG (`api/v1/public_api.py`) and the bucket stays
private.
"""

from hashlib import sha256
from uuid import uuid4

from sqlmodel import Session

from core.config import settings
from models.business_model import Business
from schemas.business_schema import BusinessSummaryResponse
from services import image_service, storage_service, upload_service

# Public route of the logo (api/v1/public_api.py).
PASS_LOGO_PATH = "/api/v1/public/logo"


def logo_key(business_id: int) -> str:
    # A fresh name per upload: browsers and CDNs never serve a stale cached logo.
    return f"businesses/{business_id}/logo/{uuid4().hex}.webp"


def logo_version(reference: str) -> str:
    """Short fingerprint of the stored reference: changes when the logo does.

    It rides in the URL query so a cached copy is dropped after an upload.
    """
    return sha256(reference.encode()).hexdigest()[:8]


def pass_logo_url(business: Business) -> str | None:
    """Stable, public URL of the business logo, or None when it has none.

    Used by the Google Wallet pass and by the card email. A stored key cannot
    be handed over as is (the signed URL expires in an hour and the email
    outlives it), so the URL points at the API route that serves the PNG.
    """
    if not business.logo_url:
        return None
    if not storage_service.is_storage_key(business.logo_url):
        return business.logo_url
    base = settings.frontend_public_url.rstrip("/")
    return f"{base}{PASS_LOGO_PATH}/{business.id}.png?v={logo_version(business.logo_url)}"


def business_summary(business: Business) -> BusinessSummaryResponse:
    """The business as the frontend sees it, with a usable logo URL."""
    summary = BusinessSummaryResponse.model_validate(business)
    return summary.model_copy(update={"logo_url": storage_service.public_url(business.logo_url)})


def set_logo(session: Session, business: Business, data: bytes) -> Business:
    """Store the processed image and point the business at it.

    Raises image_service.ImageRejected or storage_service.StorageUnavailable.
    """
    upload_service.replace_image(
        session,
        business,
        "logo_url",
        logo_key(business.id),
        data,
        max_dimension=image_service.LOGO_MAX_DIMENSION,
    )
    return business


def remove_logo(session: Session, business: Business) -> Business:
    upload_service.remove_image(session, business, "logo_url")
    return business

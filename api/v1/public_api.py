"""Router for /api/v1/public: assets the outside world loads, with no session.

Today it serves one thing: the business logo as the square PNG that the Google
Wallet pass and the card email need (`services/logo_service.pass_logo_url`).
Those two live outside the browser session, so a signed storage URL does not
work — it expires in an hour. The API hands out the bytes instead and the bucket
stays private.

The logo is the business's brand, not customer data: the URL carries the
business id and nothing else, and it answers 404 while the business is
suspended, the same rule the public card follows.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from api.v1.dependencies import SessionDep
from core.config import settings
from core.errors import ApiError, ErrorCode
from core.rate_limit import SlidingWindowLimiter
from models.business_model import Business, BusinessStatus
from services import image_service, storage_service

# One day and immutable: the URL carries a version of the stored key
# (`logo_service.logo_version`), so a new logo is a new URL.
LOGO_CACHE = {"Cache-Control": "public, max-age=86400, immutable"}
# A missing logo is not cached: storage may come back.
NO_CACHE = {"Cache-Control": "no-store"}

asset_limiter = SlidingWindowLimiter(window_seconds=60)


def asset_guard(request: Request) -> None:
    """Per-IP limit, shared budget with the public card endpoints' setting.

    Images are cached by the browser and by Cloudflare, so the real traffic is
    far below the limit; it only stops a loop from hammering storage.
    """
    client_ip = request.client.host if request.client else "unknown"
    wait = asset_limiter.hit(client_ip, settings.card_rate_limit_per_minute)
    if wait is not None:
        raise ApiError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            code=ErrorCode.RATE_LIMITED,
            headers={"Retry-After": str(wait)},
        )


router = APIRouter(prefix="/public", tags=["public"], dependencies=[Depends(asset_guard)])


def _no_logo() -> HTTPException:
    """404 without a `code`: nothing in the frontend maps this route."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Logo not found", headers=NO_CACHE
    )


@router.get(
    "/logo/{business_id}.png",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}}, "description": "The business logo, square PNG"},
        404: {"description": "The business has no stored logo"},
    },
)
def business_logo(business_id: int, session: SessionDep) -> Response:
    """The logo of a business, ready for Google Wallet and for email."""
    business = session.get(Business, business_id)
    if business is None or business.status == BusinessStatus.SUSPENDED:
        raise _no_logo()
    reference = business.logo_url
    if not reference or not storage_service.is_storage_key(reference):
        # No logo at all, or an external URL the caller can use directly.
        raise _no_logo()
    try:
        png = image_service.to_pass_png(storage_service.get_object(reference))
    except storage_service.StorageUnavailable, image_service.ImageRejected:
        raise _no_logo() from None
    return Response(content=png, media_type=image_service.PNG_CONTENT_TYPE, headers=LOGO_CACHE)

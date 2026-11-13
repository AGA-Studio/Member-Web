"""Router for /api/v1/card: the public digital card, opened from the emailed link.

No session and no cookie: the token in the URL is the only key, and the business
comes from the link. Every answer (errors too) carries `Cache-Control: no-store`,
and each IP gets `CARD_RATE_LIMIT_PER_MINUTE` requests per minute.
"""

from fastapi import APIRouter, Depends, Request, Response, status

from api.v1.dependencies import SessionDep
from core.config import settings
from core.errors import ApiError, ErrorCode
from core.rate_limit import SlidingWindowLimiter
from schemas.card_schema import PublicCardResponse
from services import card_service
from services.card_service import NO_STORE

public_limiter = SlidingWindowLimiter(window_seconds=60)


def public_guard(request: Request, response: Response) -> None:
    """Per-IP limit and no caching, for every public card endpoint."""
    response.headers.update(NO_STORE)
    client_ip = request.client.host if request.client else "unknown"
    wait = public_limiter.hit(client_ip, settings.card_rate_limit_per_minute)
    if wait is not None:
        raise ApiError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            code=ErrorCode.RATE_LIMITED,
            headers={**NO_STORE, "Retry-After": str(wait)},
        )


router = APIRouter(prefix="/card", tags=["card"], dependencies=[Depends(public_guard)])


@router.get("/{token}", response_model=PublicCardResponse)
def get_card(token: str, session: SessionDep) -> PublicCardResponse:
    """What is needed to draw the card. Never email, phone, points, cashback or ids."""
    return card_service.public_card(session, token)

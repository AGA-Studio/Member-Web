"""Router for /api/v1/registration: public business sign-up (issue #69).

No session. The checks run cheapest first, and before the body is used:

1. `REGISTRATION_ENABLED` off → 403 `registration_closed`.
2. More than `REGISTRATION_RATE_LIMIT_PER_HOUR` attempts from the IP → 429
   `rate_limited` with `Retry-After` (every attempt counts, valid or not).
3. With `TURNSTILE_ENABLED`, the `X-Turnstile-Token` header → 400 `turnstile_failed`.

There is no auto-login: the frontend sends the new admin to the normal login,
which keeps Turnstile, the H4 lock and the httpOnly cookie on one path.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from api.v1.dependencies import SessionDep
from core.config import settings
from core.errors import ApiError, ErrorCode
from core.rate_limit import SlidingWindowLimiter
from schemas.registration_schema import RegistrationCreate, RegistrationResponse
from services import registration_service
from services.turnstile_service import verify_turnstile

registration_limiter = SlidingWindowLimiter(window_seconds=3600)


def registration_guard(
    request: Request,
    turnstile_token: Annotated[str | None, Header(alias="X-Turnstile-Token")] = None,
) -> None:
    if not settings.registration_enabled:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is closed",
            code=ErrorCode.REGISTRATION_CLOSED,
        )
    client_ip = request.client.host if request.client else "unknown"
    wait = registration_limiter.hit(client_ip, settings.registration_rate_limit_per_hour)
    if wait is not None:
        raise ApiError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            code=ErrorCode.RATE_LIMITED,
            headers={"Retry-After": str(wait)},
        )
    if not verify_turnstile(turnstile_token):
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="turnstile_failed",
            code=ErrorCode.TURNSTILE_FAILED,
        )


router = APIRouter(prefix="/registration", tags=["registration"])


@router.post(
    "/create",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(registration_guard)],
)
def create(data: RegistrationCreate, session: SessionDep) -> RegistrationResponse:
    """Business + first admin + three empty tiers + plan, in one transaction."""
    return registration_service.register(session, data)

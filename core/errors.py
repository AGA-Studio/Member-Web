"""Business errors with a stable `code` (API contract, section 1.2).

The frontend picks the message to show from `code`, never from the wording of
`detail`, so `detail` can be reworded without breaking it:

    {"detail": "Business suspended", "code": "business_suspended"}

Field validation errors keep FastAPI's default 422 shape (`detail` as a list).
"""

from enum import StrEnum

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    INVALID_CREDENTIALS = "invalid_credentials"
    LOGIN_LOCKED = "login_locked"
    BUSINESS_SUSPENDED = "business_suspended"
    USER_INACTIVE = "user_inactive"
    NOT_AUTHENTICATED = "not_authenticated"
    EMAIL_TAKEN = "email_taken"


class ApiError(HTTPException):
    """An HTTPException that also carries a stable `code` for the frontend."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: ErrorCode,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=exc.headers,
    )


def setup_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)

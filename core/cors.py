"""CORS: lets the frontend (Next.js) call the API sending the session cookie."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings


def setup_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Required so the browser sends the httpOnly cookie.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

"""Member+ API entry point.

Development:
    uv run alembic upgrade head             # create/update tables
    uv run uvicorn main:app --reload        # http://127.0.0.1:8000/docs

Layout:
    core/     settings, CORS and security (Argon2id + JWT)
    db/       database engine and session
    migrations/  Alembic migrations (schema changes)
    models/   tables (SQLModel, table=True)
    schemas/  input/output DTOs (Pydantic)
    api/v1/   versioned routers; register every new module in API_V1_ROUTERS
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.v1 import auth_api, checkout_api, customer_api, movement_api, tier_api, user_api
from core.config import settings
from core.cors import setup_cors
from core.errors import setup_error_handlers
from db.database import check_database_connection

API_V1_PREFIX = "/api/v1"

# Order = order shown in /docs.
API_V1_ROUTERS = [
    auth_api.router,
    user_api.router,
    tier_api.router,
    customer_api.router,
    checkout_api.router,
    movement_api.router,
    # Next MVP module (H1–H3):
    # platform_api.router,
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: make sure the database answers. Tables are created by
    # `alembic upgrade head`, never by the app.
    check_database_connection()
    yield
    # Shutdown: nothing to release yet.


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API for Member+, the multi-business membership SaaS.",
        lifespan=lifespan,
    )

    setup_cors(app)
    setup_error_handlers(app)

    for router in API_V1_ROUTERS:
        app.include_router(router, prefix=API_V1_PREFIX)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

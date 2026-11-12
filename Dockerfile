# syntax=docker/dockerfile:1
# Imagen de producción del API de Member+.
#   docker build -t memberplus-api .
#   docker run -p 8000:8000 -e DATABASE_URL=... -e SECRET_KEY=... memberplus-api
#
# El esquema lo aplica Alembic al arrancar (ver docker/entrypoint.sh); la app
# nunca crea tablas.

# ---------- Etapa 1: dependencias y bytecode ----------
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Solo el manifiesto: esta capa se reutiliza mientras no cambie el lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY main.py alembic.ini ./
COPY api/ ./api/
COPY core/ ./core/
COPY db/ ./db/
COPY models/ ./models/
COPY schemas/ ./schemas/
COPY services/ ./services/
COPY migrations/ ./migrations/
COPY docker/ ./docker/

RUN uv sync --locked --no-dev

# Guard: importing the app fails if a package folder was not copied above
# (it happened with services/). Better a failed build than a published image
# that crashes on start. SECRET_KEY is a throwaway value, only to load settings.
RUN SECRET_KEY=build-check-only /app/.venv/bin/python -c "import main"

# ---------- Etapa 2: runtime ----------
FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000

# Usuario sin privilegios: el contenedor no necesita root para nada.
RUN useradd --create-home --uid 10001 app

WORKDIR /app

COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

# slim no trae curl ni wget: el healthcheck usa la stdlib y respeta $PORT,
# el mismo que usa el entrypoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT', '8000')}/health\", timeout=3)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]

# Member-Web

Backend de **Member+**, una plataforma SaaS para que varios negocios administren las membresías de sus clientes.

Frontend: [Member-Plus-Frontend](https://github.com/AGA-Studio/Member-Plus-Frontend)

## Stack

FastAPI · SQLModel · PostgreSQL 18 · Argon2id · JWT · Python 3.14 · uv

## Requisitos

- [uv](https://docs.astral.sh/uv/)
- Docker

## Instalación

```bash
cp .env.example .env          # cambia SECRET_KEY
uv sync
docker compose up -d          # PostgreSQL en localhost:5433
uv run uvicorn main:app --reload
```

Documentación de la API: <http://127.0.0.1:8000/docs>

## Pruebas

```bash
uv run pytest
uv run ruff check .
```

## Documentación

Arquitectura, modelo de datos y flujos: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

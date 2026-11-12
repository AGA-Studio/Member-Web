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
uv run alembic upgrade head   # crea o actualiza las tablas
uv run python -m scripts.seed # datos de demo (se puede correr varias veces)
uv run uvicorn main:app --reload
```

Documentación de la API: <http://127.0.0.1:8000/docs>

### Usuarios de demo

En desarrollo, el seed usa la contraseña `demo12345` (o la de `SEED_PASSWORD` en el `.env`).

| Usuario | Rol | Negocio |
|---------|-----|---------|
| `owner@memberplus.mx` | Dueño de plataforma | — |
| `admin@cafe-aurora.mx` | Administrador | Café Aurora |
| `caja@cafe-aurora.mx` | Empleado de caja | Café Aurora |
| `admin@gimnasio-titan.mx` | Administrador | Gimnasio Titán |

## Pruebas

```bash
uv run pytest
uv run ruff check .
```

## Documentación

- Arquitectura, modelo de datos y flujos: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Pruebas, resultados y hallazgos: [docs/TESTING.md](docs/TESTING.md)
- Migraciones de base de datos: [docs/MIGRATIONS.md](docs/MIGRATIONS.md)
- Integración continua (GitHub Actions): [docs/CI.md](docs/CI.md)
- Despliegue (imagen en GHCR y Coolify): [docs/DEPLOY.md](docs/DEPLOY.md)

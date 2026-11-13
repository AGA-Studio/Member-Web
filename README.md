<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/logo-on-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/brand/logo-on-light.png">
    <img src="docs/brand/logo-on-light.png" alt="Member+" width="240">
  </picture>
</p>

<h3 align="center">Member+ · API</h3>

<p align="center">
  <em>Cada cliente reconocido, cada cobro rápido.</em><br>
  SaaS multi-negocio de membresías · Universidad Tecnológica de Tijuana · grupo 9C
</p>

<p align="center">
  <a href="https://github.com/AGA-Studio/Member-Web/actions/workflows/ci.yml"><img src="https://github.com/AGA-Studio/Member-Web/actions/workflows/ci.yml/badge.svg?branch=main" alt="Estado del CI"></a>
  <a href="docs/DEPLOY.md"><img src="https://img.shields.io/badge/imagen-ghcr.io-2496ED?logo=docker&logoColor=white" alt="Imagen en GHCR"></a>
  <img src="https://img.shields.io/badge/checks-3%20obligatorios-0062f2" alt="Tres checks obligatorios">
  <br>
  <a href="https://www.python.org"><img src="https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white" alt="Python 3.14"></a>
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.162-009688?logo=fastapi&logoColor=white" alt="FastAPI 0.162"></a>
  <a href="https://www.postgresql.org"><img src="https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL 18"></a>
  <a href="https://sqlmodel.tiangolo.com"><img src="https://img.shields.io/badge/SQLModel-0.0.48-8A2BE2" alt="SQLModel 0.0.48"></a>
  <a href="https://docs.astral.sh/uv/"><img src="https://img.shields.io/badge/uv-0.11-4B8BBE" alt="uv 0.11"></a>
</p>

---

Member+ es una plataforma SaaS donde varios negocios administran sus membresías: clientes, tarjetas
por nivel y compras con descuento, puntos y cashback. El empleado cobra en caja leyendo el **QR impreso**
de la tarjeta.

Este repositorio es **solo el API**. La interfaz vive en
[Member-Plus-Frontend](https://github.com/AGA-Studio/Member-Plus-Frontend) y consume este servicio a
través de `/api/v1`; en producción el navegador pide `/api/*` al frontend y Next lo reescribe aquí.

Dos reglas que atraviesan todo el código:

- **Multi-negocio por token.** Cada tabla de negocio lleva `business_id`, que sale **siempre** del token
  (dependencia `BusinessId`), nunca del cuerpo ni de la URL. Un recurso de otro negocio responde 404.
- **La sesión es una cookie httpOnly** con JWT propio y Argon2id; no hay NextAuth ni Supabase. El lector
  ESP32 usa un token de dispositivo distinto, atado a su negocio.

## Stack

| Pieza | Versión |
|---|---|
| Python | 3.14 |
| FastAPI | 0.162 |
| SQLModel + SQLAlchemy (síncrono) | 0.0.48 |
| PostgreSQL | 18 |
| Alembic (migraciones) | 1.20 |
| uv (paquetes y entorno) | 0.11 |

La app **no crea tablas al arrancar**: el esquema lo maneja Alembic y las migraciones se aplican con
`alembic upgrade head` (en Docker, en el entrypoint; si fallan, la API no arranca).

## Empezar

Requisitos: [uv](https://docs.astral.sh/uv/) y Docker.

```bash
cp .env.example .env          # cambia SECRET_KEY
uv sync
docker compose up -d          # PostgreSQL en localhost:5433
uv run alembic upgrade head   # crea o actualiza las tablas
uv run python -m scripts.seed # datos de demo (se puede correr varias veces)
uv run uvicorn main:app --reload
```

Documentación interactiva de la API: <http://127.0.0.1:8000/docs> · salud: <http://127.0.0.1:8000/health>

### Usuarios de demo

En desarrollo, el seed usa la contraseña `demo12345` (o la de `SEED_PASSWORD` en el `.env`).

| Usuario | Rol | Negocio |
|---------|-----|---------|
| `owner@memberplus.mx` | Dueño de plataforma | — |
| `admin@cafe-aurora.mx` | Administrador | Café Aurora |
| `caja@cafe-aurora.mx` | Empleado de caja | Café Aurora |
| `admin@gimnasio-titan.mx` | Administrador | Gimnasio Titán |

## Comandos

| Comando | Qué hace |
|---|---|
| `uv run pytest -q` | Pruebas (SQLite temporal por defecto) |
| `uv run ruff check . && uv run ruff format .` | Lint y formato |
| `uv run alembic upgrade head` | Aplica migraciones |
| `uv run alembic revision --autogenerate -m "..."` | Genera una migración (revisarla a mano) |
| `uv run alembic check` | Falla si los modelos y las migraciones divergen |
| `uv run python -m scripts.seed` | Datos de demo con dos negocios |

## API

Prefijo `/api/v1`, salvo `/health`.

| Grupo | Rutas |
|---|---|
| Sistema | `GET /health` |
| Auth | `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` |
| Usuarios | `GET /user/list` · `POST /user/create` · `GET /user/{id}` · `PATCH /user/{id}/update` |

Las rutas siguen la forma `/<recurso>/<acción>`. El contrato completo, payloads y errores por módulo
están en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Estructura

```
main.py            create_app, lifespan, CORS y el registro de API_V1_ROUTERS
core/              configuración, CORS y seguridad (Argon2id + JWT)
db/                engine, comprobación de conexión y sesión de SQLModel
models/            tablas (una por archivo, *_model.py)
schemas/           DTOs de entrada y salida (*_schema.py)
api/v1/            dependencias y un router por módulo
services/          lógica de negocio y cálculo
migrations/        Alembic: env.py y versions/
scripts/           seed de demo y revisor de PRs
tests/             pytest: api, db, unit, rules
```

## Documentación

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — arquitectura, modelo de datos y flujos.
- [docs/TESTING.md](docs/TESTING.md) — pruebas, resultados y hallazgos.
- [docs/MIGRATIONS.md](docs/MIGRATIONS.md) — Alembic, cómo aplicar y revertir.
- [docs/CI.md](docs/CI.md) — los jobs, qué corre en cada PR y el revisor automático.
- [docs/DEPLOY.md](docs/DEPLOY.md) — imagen en GHCR, Coolify, migraciones y rollback.
- [docs/REVISION.md](docs/REVISION.md) — criterios de revisión del proyecto.

## Flujo de trabajo

`main` es la única rama: trabajo en `feature/<nombre>`, PR a `main` y merge del equipo. El CI exige
`lint`, `test` y `test (postgres)`; el revisor automático comenta pero no bloquea.

**Mergear a `main` despliega**: `image.yml` publica la imagen en GHCR y llama al deploy webhook de
Coolify, que apunta al tag móvil `latest`. Los releases (`gh release create vX.Y.Z`) marcan el hito y
publican `0.1.0`/`0.1`, pero ya no son la vía de despliegue.

Proyecto académico de la UTT · *Desarrollo Web Integral* · grupo **9C** · equipo **AGA-Studio**.

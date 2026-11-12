# AGENTS.md

Guía para agentes de IA (Claude Code, Codex, Copilot, etc.) que trabajan en este repositorio.

## Proyecto

**Member+** es un SaaS multi-negocio de membresías: cada negocio administra clientes, tarjetas por nivel, puntos, descuento y cashback, y cobra en caja leyendo un QR. Este repositorio es **solo el backend** (API). El frontend está en [Member-Plus-Frontend](https://github.com/AGA-Studio/Member-Plus-Frontend).

Proyecto académico de la UTT (Desarrollo Web Integral, grupo 9C).

### Fuentes de verdad

La documentación del producto vive en la wiki de Outline (`wiki.neyzt.org`, colección **9no**, accesible con el MCP `outline`). Prioridad:

1. **MVP**: alcance, hitos y criterios de aceptación vigentes.
2. **Decisiones por validar**: decisiones tomadas (✅) y pendientes.
3. **Pantallas**: pantallas, roles y flujos.

Desactualizados, no usar como referencia: el **ERS**, el calendario de la *Guía de desarrollo* y `docs/00-auditoria-proyecto.md` (propone Supabase y reconocimiento facial; ambos se descartaron).

### Decisiones que no se discuten

- Sin Supabase: PostgreSQL 18 propio (Docker Compose) y JWT propio.
- **Sin reconocimiento facial.** La cámara solo lee el QR de la tarjeta.
- Tres roles: `platform` (nosotros), `admin` y `employee`. Los clientes del negocio no inician sesión.
- La compra es solo monto y concepto: sin catálogo ni inventario.
- Fuera de alcance: pagos en línea, sucursales, app móvil, portal del cliente, canje de puntos.

## Stack y comandos

FastAPI · SQLModel (síncrono) · PostgreSQL 18 · pwdlib (Argon2id) · PyJWT · Python 3.14 · **uv**

```bash
uv sync                              # instalar dependencias
docker compose up -d                 # PostgreSQL en localhost:5433
uv run uvicorn main:app --reload     # API en http://127.0.0.1:8000/docs
uv run pytest                        # pruebas (SQLite temporal)
uv run ruff check . && uv run ruff format .
uv add <paquete>                     # nueva dependencia (uv add --dev para desarrollo)
```

- Las dependencias se manejan **solo** con `pyproject.toml` + `uv.lock`. No crear `requirements.txt`. El equipo trabaja en Linux, macOS y Windows.
- `uv.lock` siempre se sube.

## Estructura

```
main.py          create_app, lifespan, CORS, API_V1_ROUTERS
core/            config.py (Settings/.env), cors.py, security.py (Argon2id + JWT)
db/database.py   engine, create_db_and_tables, get_session
models/          tablas SQLModel (table=True), una por archivo: <nombre>_model.py
schemas/         DTOs Pydantic: <nombre>_schema.py (XCreate, XUpdate, XResponse)
api/v1/          dependencies.py y un router por módulo: <nombre>_api.py
tests/           pytest
docs/            documentación con diagramas Mermaid
```

## Convenciones de código

- **Código en inglés** (nombres, comentarios, mensajes de error). **Documentación en español.**
- Rutas con la forma `/<recurso en singular>/<acción>`: `/user/create`, `/user/list`, `/user/{id}`, `/user/{id}/update`.
- Cada módulo nuevo: modelo → importarlo en `models/__init__.py` → schemas → router → agregarlo a `API_V1_ROUTERS` en `main.py` → pruebas.

### Aislamiento multi-negocio (obligatorio)

- Toda tabla con datos de un negocio lleva `business_id`.
- `business_id` **siempre** sale del token (dependencia `BusinessId`), nunca del cuerpo ni de la URL. No aparece en schemas de entrada.
- Toda consulta filtra por `business_id`. Un recurso de otro negocio responde **404**.
- Cada módulo nuevo incluye una prueba de que un negocio no ve datos de otro.

### Pruebas

- Guía completa, fixtures y lista mínima por módulo: `docs/TESTING.md`.
- Usar las fixtures de `tests/conftest.py` (`client`, `two_businesses`, `make_user`, `login()`); sin mocks.
- Las pruebas deben pasar en SQLite y en PostgreSQL (`TEST_DATABASE_URL` hacia la base `memberplus_test`, nunca la de desarrollo).
- Un problema encontrado y no corregido se registra como prueba `xfail(strict=True)` en `tests/api/test_known_issues.py` y en la tabla de hallazgos de `docs/TESTING.md`.
- Los schemas de salida nunca exponen `hashed_password` ni tokens.

## Documentación

- Todo cambio en modelos, endpoints o flujos se refleja en `docs/ARCHITECTURE.md` **en el mismo commit o en el siguiente**.
- Los diagramas van en **Mermaid**: `erDiagram` para tablas, `sequenceDiagram` para flujos entre componentes, `flowchart` para estructura y procesos, `stateDiagram-v2` para estados.
- Etiquetas con caracteres especiales van entre comillas (`A["/user/create"]`).

## Git

### Ramas

- `main`: estable. `develop`: integración.
- Trabajo nuevo en `feature/<descripcion-corta>` creada desde `develop`, y PR hacia `develop`.
- No hacer commit directo en `main` ni en `develop`. No hacer push sin que el usuario lo pida.

### Commits

Commits **pequeños y frecuentes**: uno por cada cambio lógico terminado (un modelo, un endpoint, sus pruebas, su documentación), no uno gigante al final. Antes de cada commit, `ruff` y `pytest` en verde.

Formato: `<prefijo>: <verbo en infinitivo y minúscula> <qué>`, una línea, **máximo ~60 caracteres**, sin punto final.

| Prefijo | Uso |
|---------|-----|
| `feat` | Funcionalidad nueva |
| `fix` | Corrección de un error |
| `hotfix` | Corrección urgente en `main` |
| `refactor` | Cambio de código sin cambiar comportamiento |
| `test` | Pruebas |
| `docs` | Solo documentación |
| `chore` | Configuración, dependencias, mantenimiento |

Ejemplos:

```
feat: agregar modelo de cliente
feat: agregar endpoint /customer/create
test: probar aislamiento de clientes entre negocios
docs: documentar flujo de caja en mermaid
fix: validar vigencia al renovar membresía
```

No mezclar en un commit cosas de distinto prefijo (por ejemplo, un `feat` y un `chore` de dependencias van separados).

### Nunca subir

`.env`, `.venv/`, bases SQLite (`*.db`), `.mcp.json`, `.claude/settings.local.json`, credenciales o tokens.

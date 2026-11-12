# AGENTS.md

Guía para agentes de IA (Claude Code, Codex, Copilot, etc.) que trabajan en este repositorio.

## Proyecto

**Member+** es un SaaS multi-negocio de membresías: cada negocio administra clientes, tarjetas por
nivel, puntos, descuento y cashback, y cobra en caja leyendo el QR de la tarjeta. Este repositorio es
**solo el backend** (API); el frontend está en
[Member-Plus-Frontend](https://github.com/AGA-Studio/Member-Plus-Frontend). Proyecto académico de la
UTT (Desarrollo Web Integral, grupo 9C).

### Fuentes de verdad

La documentación del producto vive en la wiki de Outline (`wiki.neyzt.org`, colección **9no**,
accesible con el MCP `outline`). Orden:

1. **Decisiones por validar** — la bitácora del modelo SaaS. Una casilla marcada **✅** está decidida
   y no se reabre. Una casilla **sin marcar sigue abierta**: no la resuelvas por tu cuenta, pregunta.
2. **MVP** — dice *qué parte* se construye primero y con qué criterio. Está en estado **Propuesta,
   pendiente de aprobación del equipo**: si choca con una casilla ✅, gana la casilla; avisa la
   contradicción en vez de elegir en silencio.
3. **Requisitos de referencia** (RF/RNF) y **Pantallas**.
- Diseño y marca (color, tipografía, tono, componentes): **Identidad de marca**, solo si tocas textos o UX.

No usar como referencia: el **ERS**, el calendario y los responsables de la *Guía de desarrollo* (son
de relleno) y `docs/00-auditoria-proyecto.md` (propone Supabase y reconocimiento facial, ambos
descartados). La arquitectura vigente del repo es `docs/ARCHITECTURE.md`.

### Decisiones cerradas

- Sin Supabase: **PostgreSQL 18 propio** (Docker Compose) y JWT propio en cookie httpOnly con
  Argon2id. Sin NextAuth ni pasarela de pagos.
- **Sin reconocimiento facial.** La cámara —ESP32 o webcam— solo lee el QR; el lector identifica la
  tarjeta, no a la persona. No se guardan fotos ni datos biométricos.
- Tres roles: `platform` (nosotros), `admin` y `employee`. Los clientes del negocio no inician sesión.
- La compra en caja es **monto y concepto libre**: sin catálogo ni inventario. La tarjeta se
  identifica por **QR impreso o tecleo manual del código corto**.
- **Los puntos son un historial de movimientos, no una columna del cliente**: el saldo se calcula.
  Orden del cálculo: descuento primero; puntos y cashback sobre lo ya descontado.
- Cashback: si el negocio lo habilita, se acumula y se puede aplicar en la siguiente compra con
  aprobación del cliente.
- Fuera de alcance: pagos en línea, sucursales, app móvil, portal del cliente, canje de puntos,
  reportes.

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

- Las dependencias se manejan **solo** con `pyproject.toml` + `uv.lock`. No crear `requirements.txt`.
  El equipo trabaja en Linux, macOS y Windows; `uv.lock` siempre se sube.
- El proyecto es **síncrono**. No conviertas nada a `async` sin preguntar.
- **Migraciones**: hoy las tablas se crean con `create_db_and_tables` en el `lifespan`. El MVP exige
  una migración inicial y **la herramienta no está decidida**: no elijas una por tu cuenta.
- **CI**: el MVP pide Ruff + pytest en cada PR. `.github/workflows/` todavía no existe; si lo creas,
  es un archivo compartido: avisa antes.

## Estructura

```
main.py          create_app, lifespan, CORS, API_V1_ROUTERS
core/            config.py (Settings/.env), cors.py, security.py (Argon2id + JWT)
db/database.py   engine, create_db_and_tables, get_session
models/          tablas SQLModel (table=True), una por archivo: <nombre>_model.py
schemas/         DTOs Pydantic: <nombre>_schema.py (XCreate, XUpdate, XResponse)
services/        lógica de negocio y cálculo; se crea con el primer módulo que la necesite
api/v1/          dependencies.py y un router por módulo: <nombre>_api.py
tests/           pytest
docs/            documentación con diagramas Mermaid
```

Ningún router es gordo: el router valida y delega. El cálculo (descuento, puntos, cashback) vive en
`services/`, que es lo que se mide en cobertura (MVP: ≥ 60 %).

## Convenciones de código

- **Código en inglés** (nombres, comentarios, mensajes de error). **Documentación en español.** La
  wiki escribe `negocio_id`; en código es `business_id`: es lo mismo.
- Rutas con la forma `/<recurso en singular>/<acción>`: `/user/create`, `/user/list`, `/user/{id}`,
  `/user/{id}/update`.
- Cada módulo nuevo: modelo → importarlo en `models/__init__.py` → schemas → servicio → router →
  agregarlo a `API_V1_ROUTERS` en `main.py` → pruebas.

### Aislamiento multi-negocio (obligatorio)

- Toda tabla con datos de un negocio lleva `business_id`.
- `business_id` **siempre** sale del token (dependencia `BusinessId`), nunca del cuerpo ni de la URL.
  No aparece en schemas de entrada.
- Toda consulta filtra por `business_id`. Un recurso de otro negocio responde **404**.
- RLS en la base como defensa en profundidad, además del filtro en la aplicación (lo pide el MVP).
- Cada módulo nuevo incluye una prueba de que un negocio no ve datos de otro.
- Los schemas de salida nunca exponen `hashed_password` ni tokens.

## Documentación

- Todo cambio en modelos, endpoints o flujos se refleja en `docs/ARCHITECTURE.md` **en el mismo commit
  o en el siguiente**.
- Los diagramas van en **Mermaid**: `erDiagram` para tablas, `sequenceDiagram` para flujos entre
  componentes, `flowchart` para estructura y procesos, `stateDiagram-v2` para estados.
- Etiquetas con caracteres especiales van entre comillas (`A["/user/create"]`).

## Git

- `main` estable, `develop` integración. Trabajo nuevo en `feature/<descripcion-corta>` desde
  `develop`, PR hacia `develop`. Nada de commits directos en `main` ni en `develop`.
- No hacer push, merge ni tocar el remoto sin que el usuario lo pida.
- Commits **pequeños**, uno por cambio lógico (un modelo, un endpoint, sus pruebas, su documentación),
  con `ruff` y `pytest` en verde. Formato: `<prefijo>: <verbo en infinitivo y minúscula> <qué>`, una
  línea, ~60 caracteres, en español.
- Prefijos: `feat`, `fix`, `hotfix`, `refactor`, `test`, `docs`, `chore`. No mezcles prefijos en el
  mismo commit. Ejemplo: `feat: agregar endpoint /customer/create`.
- Nunca subir: `.env`, `.venv/`, bases SQLite (`*.db`), `.mcp.json`, `.claude/settings.local.json`,
  credenciales o tokens.

# Pruebas del backend — Member+

Documentación de la suite de pruebas automatizadas del backend: qué se prueba, cómo está organizada, cómo correrla, los resultados de la última ejecución y los hallazgos encontrados.

> Arquitectura general del backend: [ARCHITECTURE.md](ARCHITECTURE.md).

## Índice

1. [Resumen](#1-resumen)
2. [Cómo correr las pruebas](#2-cómo-correr-las-pruebas)
3. [Estrategia](#3-estrategia)
4. [Infraestructura de pruebas](#4-infraestructura-de-pruebas)
5. [Casos de prueba](#5-casos-de-prueba)
6. [Resultados de la ejecución](#6-resultados-de-la-ejecución)
7. [Hallazgos](#7-hallazgos)
8. [Cómo agregar pruebas](#8-cómo-agregar-pruebas)

---

## 1. Resumen

| Métrica | Valor |
|---------|-------|
| Fecha de ejecución | 12 de noviembre de 2026 |
| Pruebas | **622**, todas pasan (0 `xfail`); conteo del 13 nov 2026 con niveles, clientes, caja, movimientos, plataforma y entrega de la tarjeta digital (enlace, correo y Google Wallet) |
| Fallas | **0** |
| Cobertura de líneas y ramas | **100 %** en `api/`, `core/`, `models/`, `schemas/`, `services/` y `scripts/seed.py`. `scripts/review_pr.py` (revisor del CI) queda en 60 %, por eso el total marca 92 % |
| Bases de datos probadas | SQLite y **PostgreSQL 18.6** |
| Tiempo | ~17 s en SQLite · ~42 s en PostgreSQL (equipo local) |
| Criterio del MVP "0 filas de otro negocio" | ✅ Cumplido (7 pruebas de usuarios + 4 de niveles + 9 de clientes + 4 de caja + 3 de movimientos + 3 del enlace a la tarjeta) |
| Migraciones (Alembic) | ✅ Suben, bajan, convierten datos y coinciden con los modelos (9 pruebas) |
| Hallazgos | ✅ Los 7 corregidos (H1–H7) |

No quedan `xfail`: los 7 [hallazgos](#7-hallazgos) se corrigieron y sus pruebas pasaron a la suite normal.

```mermaid
pie showData
    title Pruebas por archivo (217)
    "test_user.py" : 53
    "test_auth.py" : 46
    "test_validators.py" : 24
    "test_seed.py" : 22
    "test_security.py" : 17
    "test_login_limit.py" : 12
    "test_migrations.py" : 9
    "test_config.py" : 9
    "test_system.py" : 8
    "test_isolation.py" : 7
    "test_auth_service.py" : 6
    "test_models.py" : 4
```

---

## 2. Cómo correr las pruebas

### Con SQLite (por defecto)

No necesita Docker ni `.env`: cada ejecución crea una base SQLite temporal.

```bash
uv run pytest                 # toda la suite
uv run pytest -v              # con el nombre de cada prueba
uv run pytest -rx             # muestra el motivo de cada xfail
uv run pytest --cov           # con reporte de cobertura
uv run pytest tests/api/test_isolation.py      # un archivo
uv run pytest -k "login"                       # por nombre
```

### Con PostgreSQL

La misma suite corre contra PostgreSQL real con la variable `TEST_DATABASE_URL`. Usa una **base aparte** (`memberplus_test`): las pruebas borran y recrean las tablas antes de cada caso, así que **nunca** se debe apuntar a la base de desarrollo.

```bash
docker compose up -d
docker exec memberplus-db createdb -U memberplus memberplus_test     # solo la primera vez

# Linux / macOS
TEST_DATABASE_URL=postgresql+psycopg://memberplus:memberplus@localhost:5433/memberplus_test uv run pytest

# Windows (PowerShell)
$env:TEST_DATABASE_URL="postgresql+psycopg://memberplus:memberplus@localhost:5433/memberplus_test"; uv run pytest
```

### Antes de cada commit

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

### En GitHub (CI)

Lo mismo corre automáticamente en cada PR y en cada push a `main` (jobs `lint`, `test` y `test (postgres)`), y los tres son obligatorios para fusionar. Detalle en [CI.md](CI.md).

-----|-----------|
| `lint` | `ruff check` y `ruff format --check` |
| `test` | La suite completa sobre SQLite |
| `test (postgres)` | La suite completa sobre un servicio `postgres:18`, verifica que de verdad se crearon tablas en Postgres y, en una base aparte, aplica `alembic upgrade head` y `alembic check` (falla si los modelos y las migraciones no coinciden) |

Los tres jobs son **obligatorios**: el ruleset `protect-main` bloquea la fusión hacia `main` si alguno no sale en verde o si la rama no está actualizada. Un push nuevo a la misma rama cancela el run anterior, así que un run *cancelled* seguido de uno en verde es normal.

---

## 3. Estrategia

### Niveles

```mermaid
flowchart TB
    subgraph UNIT["Unitarias — tests/unit/ (60)"]
        U1["test_security.py<br/>Argon2id y JWT"]
        U2["test_config.py<br/>Settings y .env"]
        U3["test_models.py<br/>defaults y restricciones"]
        U4["test_validators.py<br/>nombres de persona"]
        U5["test_auth_service.py<br/>revocación y limpieza"]
    end

    subgraph API["De API / integración — tests/api/ (126)"]
        A1["test_system.py<br/>/health · OpenAPI · CORS"]
        A2["test_auth.py<br/>login · sesión · tokens"]
        A3["test_user.py<br/>/user: permisos y reglas"]
        A4["test_isolation.py<br/>aislamiento multi-negocio"]
        A5["test_login_limit.py<br/>5 intentos y 429"]
        A6["test_known_issues.py<br/>hallazgos abiertos (vacío)"]
    end

    subgraph DBT["De base de datos — tests/db/ (9)"]
        D1["test_migrations.py<br/>Alembic: upgrade · downgrade · sincronía"]
    end

    subgraph SCT["Scripts — tests/scripts/ (22)"]
        S1["test_seed.py<br/>datos de demo"]
    end

    UNIT --> CODE["core/ · models/"]
    API --> HTTP["TestClient (HTTP real)"] --> APP["FastAPI completo:<br/>CORS → routers → dependencias → BD"]
    DBT --> ALE["alembic command.upgrade / downgrade<br/>sobre la base de prueba"]
```

- **Unitarias:** funciones aisladas (`hash_password`, `create_access_token`, `Settings`), sin HTTP.
- **De base de datos:** aplican y revierten las migraciones de Alembic y comparan el esquema resultante con los modelos.
- **De API:** peticiones HTTP reales con `TestClient` contra la app completa: middleware de CORS, routers, dependencias de autenticación y base de datos real (SQLite o PostgreSQL). No se usan *mocks*: lo que se prueba es lo que corre en producción.

### Qué se verifica en cada endpoint

| Aspecto | Ejemplo |
|---------|---------|
| Camino feliz | Un admin crea un empleado → 201 |
| Autenticación | Sin token → 401 en **todos** los endpoints protegidos |
| Autorización por rol | `employee` y `platform` → 403 en `/user/*` |
| Aislamiento | Recurso de otro negocio → 404, igual que uno inexistente |
| Validación | Email inválido, contraseña corta o nombre con menos de 2 letras → 422 |
| Reglas de negocio | Email único, `business_id` del token, rol no editable, negocio suspendido sin acceso, un admin no se desactiva a sí mismo |
| Seguridad de la respuesta | Nunca aparece `hashed_password` |
| Efecto real | Después de cambiar la contraseña, la vieja ya no sirve |

### Códigos de respuesta esperados

```mermaid
flowchart TD
    REQ["Petición a /api/v1/user/*"] --> T{"¿Hay token en<br/>cookie o Bearer?"}
    T -- no --> E401a["401"]
    T -- sí --> V{"¿JWT válido, firmado<br/>y sin expirar?"}
    V -- no --> E401b["401"]
    V -- sí --> REV{"¿Su jti está en<br/>revoked_tokens?"}
    REV -- sí --> E401r["401 (sesión cerrada)"]
    REV -- no --> U{"¿El usuario existe?"}
    U -- no --> E401c["401"]
    U -- sí --> ACT{"¿is_active?"}
    ACT -- no --> E403a["403 Inactive user"]
    ACT -- sí --> SUS{"¿Su negocio está<br/>suspendido?"}
    SUS -- sí --> E403s["403 Business suspended"]
    SUS -- no --> R{"¿role = admin?<br/>(rol leído de la BD)"}
    R -- no --> E403b["403 Permission denied"]
    R -- sí --> B{"¿Tiene business_id?"}
    B -- no --> E403c["403 does not belong to a business"]
    B -- sí --> BODY{"¿Cuerpo válido?"}
    BODY -- no --> E422["422"]
    BODY -- sí --> OWN{"¿El recurso es<br/>de su negocio?"}
    OWN -- no --> E404["404 User not found"]
    OWN -- sí --> SELF{"¿Se desactiva<br/>a sí mismo?"}
    SELF -- sí --> E400["400 cannot deactivate<br/>your own account"]
    SELF -- no --> OK["200 / 201"]
```

Cada rama del diagrama tiene al menos una prueba.

---

## 4. Infraestructura de pruebas

### Estructura

```
tests/
├── conftest.py              Configuración, fixtures y helper login()
├── unit/
│   ├── test_security.py
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_validators.py
│   ├── test_auth_service.py
│   ├── test_customer_service.py
│   └── test_pricing_service.py
└── api/
    ├── test_system.py
    ├── test_auth.py
    ├── test_user.py
    ├── test_isolation.py
    ├── test_tier.py
    ├── test_isolation_tier.py
    ├── test_customer.py
    ├── test_isolation_customer.py
    ├── test_checkout.py
    ├── test_isolation_checkout.py
    ├── test_movement.py
    ├── test_isolation_movement.py
    ├── test_platform.py
    ├── test_login_limit.py
    ├── test_error_codes.py
    └── test_known_issues.py
├── db/
│   └── test_migrations.py
└── scripts/
    └── test_seed.py
└── rules/
    ├── helpers.py           Lectores de AST compartidos (no hay fixtures)
    ├── test_schemas.py
    ├── test_sync.py
    ├── test_routes.py
    ├── test_modules.py
    └── test_docs.py
```

### Configuración (`tests/conftest.py`)

Las variables de entorno se fijan **antes** de importar la app, porque `settings` y `engine` se crean al importarse:

| Variable | Valor en pruebas | Para qué |
|----------|------------------|----------|
| `DATABASE_URL` | `TEST_DATABASE_URL` o una SQLite temporal | Nunca tocar la base de desarrollo |
| `SECRET_KEY` | Clave fija solo para pruebas | Resultados deterministas, sin depender del `.env` |
| `CORS_ORIGINS` | `http://localhost:3000` | Probar CORS con un origen conocido |
| `COOKIE_SECURE` | `false` | `TestClient` usa HTTP |

### Fixtures

```mermaid
flowchart LR
    CLEAN["_clean_database<br/>(autouse)<br/>drop_all · create_all · dispose"]
    SES["session<br/>Session(engine)"]
    CLI["client<br/>TestClient(app)"]
    MB["make_business(name, status)"]
    MU["make_user(email, business, role,<br/>password, is_active)"]
    TWO["two_businesses<br/>escenario de la demo"]
    LOGIN["login(client, email)<br/>helper: guarda cookie<br/>y devuelve el token"]

    SES --> MB
    SES --> MU
    MB --> TWO
    MU --> TWO
    CLI --> LOGIN
```

| Fixture | Qué hace |
|---------|----------|
| `_clean_database` | Se ejecuta antes de **cada** prueba: borra y recrea las tablas con `create_all` (más rápido que migrar en cada caso) y cierra el pool de conexiones. Ninguna prueba depende de otra. Que `create_all` y las migraciones producen el mismo esquema lo garantiza `test_models_and_migrations_are_in_sync`. |
| `session` | Sesión de base de datos para preparar datos o revisar el estado final. |
| `client` | `TestClient` sobre la app completa; conserva cookies entre peticiones como un navegador. |
| `make_business` | Crea un negocio (por defecto `active`). |
| `make_user` | Crea un usuario con contraseña `password123`. Reutiliza un hash Argon2id precalculado para no recalcularlo en cada usuario (bajó la suite de 72 s a 13 s). |
| `two_businesses` | Escenario del guion de la demo del MVP (abajo). |
| `login()` | Inicia sesión; el `client` queda con la cookie y se devuelve el token para usarlo como Bearer. |

### Escenario `two_businesses`

```mermaid
flowchart TB
    subgraph A["Business A"]
        AA["admin.a@demo.mx<br/>admin"]
        EA["employee.a@demo.mx<br/>employee"]
    end
    subgraph B["Business B"]
        AB["admin.b@demo.mx<br/>admin"]
        EB["employee.b@demo.mx<br/>employee"]
    end
    P["owner@memberplus.mx<br/>platform · sin negocio"]
```

### Ciclo de una prueba de API

```mermaid
sequenceDiagram
    autonumber
    participant PY as pytest
    participant FX as fixtures
    participant DB as Base de prueba
    participant TC as TestClient
    participant APP as FastAPI

    PY->>FX: _clean_database
    FX->>DB: DROP + CREATE tablas
    FX->>FX: engine.dispose()
    PY->>FX: two_businesses
    FX->>DB: INSERT 2 negocios + 5 usuarios
    PY->>TC: login(client, "admin.a@demo.mx")
    TC->>APP: POST /api/v1/auth/login
    APP-->>TC: 200 + Set-Cookie
    PY->>TC: client.get("/api/v1/user/list")
    TC->>APP: GET con cookie
    APP->>DB: SELECT ... WHERE business_id = A
    APP-->>TC: 200 [2 usuarios]
    PY->>PY: assert
```

### Problema resuelto en la infraestructura

Al correr en PostgreSQL, una prueba fallaba con `cached plan must not change result type`. psycopg prepara las consultas que se repiten y las guarda en cada conexión del pool. Como cada prueba **recrea** las tablas, esas consultas preparadas apuntaban a tablas viejas. Se resolvió con `engine.dispose()` después de recrear el esquema. No afecta a la aplicación: en producción el esquema no cambia con conexiones abiertas.

---

## 5. Casos de prueba

Columna **Resultado**: ✅ pasa en SQLite y PostgreSQL · ⚠️ `xfail` esperado (ver [Hallazgos](#7-hallazgos)).

### 5.1 Seguridad — `tests/unit/test_security.py` (17)

**Contraseñas (Argon2id)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_hash_uses_argon2id` | El hash empieza con `$argon2id$` | ✅ |
| `test_hash_never_stores_plain_text` | La contraseña no aparece dentro del hash | ✅ |
| `test_same_password_produces_different_hashes` | Sal aleatoria: misma contraseña, hashes distintos | ✅ |
| `test_verify_correct_password` | La contraseña correcta se acepta | ✅ |
| `test_verify_wrong_password` | Una contraseña distinta se rechaza | ✅ |
| `test_verify_is_case_sensitive` | `Password123` ≠ `password123` | ✅ |
| `test_unicode_password` | Acepta `ñ`, acentos y emojis | ✅ |

**Tokens JWT**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_token_contains_expected_claims` | `sub`, `role`, `business_id`, `exp` y `jti` | ✅ |
| `test_every_token_has_a_unique_jti` | 50 tokens, 50 `jti` distintos (H2) | ✅ |
| `test_platform_token_has_null_business` | `business_id = null` para `platform` | ✅ |
| `test_default_expiration_matches_settings` | Expira en 480 min | ✅ |
| `test_custom_expiration` | Respeta `expires_delta` | ✅ |
| `test_expired_token_is_rejected` | Token vencido → `ExpiredSignatureError` | ✅ |
| `test_tampered_token_is_rejected` | Payload alterado (empleado → admin) → firma inválida | ✅ |
| `test_token_signed_with_another_key_is_rejected` | Firmado con otra clave → rechazado | ✅ |
| `test_unsigned_token_alg_none_is_rejected` | Ataque `alg: none` → rechazado | ✅ |
| `test_garbage_token_is_rejected` | Texto que no es JWT → rechazado | ✅ |

### 5.2 Configuración — `tests/unit/test_config.py` (9)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_secret_key_is_required` | Sin `SECRET_KEY` la app no arranca | ✅ |
| `test_empty_database_url_falls_back_to_sqlite` | `DATABASE_URL` vacío → `sqlite:///memberplus.db` | ✅ |
| `test_database_url_is_used_when_present` | Usa la URL de Postgres si existe | ✅ |
| `test_cors_origins_are_split_by_comma` | `"a, b ,"` → `["a", "b"]` | ✅ |
| `test_cors_origins_accept_a_list` | También acepta una lista | ✅ |
| `test_defaults` | HS256, 480 min, cookie `access_token`, `secure=false`, `development`, 5 intentos y 15 min de bloqueo | ✅ |
| `test_invalid_environment_is_rejected` | `ENVIRONMENT=staging` → error | ✅ |
| `test_login_limits_must_be_positive[...]` | `LOGIN_MAX_ATTEMPTS=0` o `LOGIN_LOCKOUT_MINUTES=0` → error (2 casos) | ✅ |

### 5.3 Modelos — `tests/unit/test_models.py` (4)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_business_defaults` | Negocio nuevo: `status=trial`, `logo_url=null`, `created_at` | ✅ |
| `test_user_defaults` | Usuario nuevo: `role=employee`, `is_active=true` | ✅ |
| `test_email_unique_constraint` | La base rechaza emails duplicados (`IntegrityError`) | ✅ |
| `test_enum_values` | Valores exactos de `Role` y `BusinessStatus` | ✅ |

### 5.3b Nombres de persona — `tests/unit/test_validators.py` (24)

Regla de H5 (`schemas/validators.py`, tipo `PersonName`): quita espacios al inicio y al final y junta los dobles; solo letras de cualquier alfabeto (con acentos y ñ), espacios, guion y apóstrofo; **mínimo 2 letras**; máximo 120 caracteres.

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_valid_names_are_normalized[...]` | Acepta `Ana`, `Iván`, `José Luis`, `María-José`, `O'Connor`, `D’Angelo`, `Ñandú`, `Bo`; `"  José   Luis  "` → `"José Luis"`; un tabulador cuenta como espacio (10 casos) | ✅ |
| `test_invalid_names_are_rejected[...]` | Rechaza vacío, solo espacios, una letra, solo guiones o apóstrofos, dígitos, símbolos, punto, guion bajo y emoji (12 casos) | ✅ |
| `test_max_length` | 120 caracteres sí, 121 no | ✅ |
| `test_error_messages` | Mensajes `at least 2 letters` y `only contain letters` | ✅ |

### 5.4 Sistema y CORS — `tests/api/test_system.py` (8)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_health` | `GET /health` → `{"status": "ok"}` | ✅ |
| `test_swagger_ui_is_served` | `/docs` responde con Swagger UI | ✅ |
| `test_openapi_exposes_exactly_the_expected_routes` | Existen exactamente las 8 rutas documentadas | ✅ |
| `test_openapi_declares_password_flow_for_swagger_authorize` | El botón *Authorize* de Swagger usa `/api/v1/auth/login` | ✅ |
| `test_unknown_route_returns_404` | Ruta inexistente → 404 | ✅ |
| `TestCors::test_preflight_from_allowed_origin` | Preflight desde el frontend: `allow-origin` + `allow-credentials: true` | ✅ |
| `TestCors::test_preflight_from_unknown_origin_is_not_allowed` | Otro origen no recibe `allow-origin` | ✅ |
| `TestCors::test_simple_request_from_allowed_origin` | Petición simple con origen permitido | ✅ |

### 5.5 Autenticación — `tests/api/test_auth.py` (52)

**Login (`POST /api/v1/auth/login`)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_login_returns_token` | 200, `token_type=bearer`, JWT con 3 partes | ✅ |
| `test_token_claims_match_user` | Los claims coinciden con el usuario y su negocio | ✅ |
| `test_login_sets_secure_session_cookie` | Cookie `HttpOnly`, `SameSite=lax`, `Max-Age=28800`, `Path=/` | ✅ |
| `test_cookie_value_equals_body_token` | La cookie y el cuerpo traen el mismo token | ✅ |
| `test_email_is_case_insensitive` | `ADMIN.A@Demo.MX` inicia sesión | ✅ |
| `test_wrong_password` | 401 `Incorrect email or password`, sin cookie | ✅ |
| `test_unknown_email_gives_same_error_as_wrong_password` | Mismo mensaje: no revela qué emails existen | ✅ |
| `test_inactive_user_cannot_login` | Usuario inactivo → 403 | ✅ |
| `test_platform_user_can_login` | `platform` entra con `business_id=null` | ✅ |
| `test_missing_fields[empty / no-password / no-username]` | Faltan campos → 422 (3 casos) | ✅ |
| `test_json_body_is_not_accepted` | El flujo OAuth2 exige formulario, no JSON → 422 | ✅ |

**Sesión actual (`GET /api/v1/auth/me`) y dependencias**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_me_with_cookie` | Funciona con la cookie (frontend) | ✅ |
| `test_me_with_bearer_header` | Funciona con `Authorization: Bearer` (Swagger, lector) | ✅ |
| `test_me_never_exposes_password_hash` | Solo devuelve los 7 campos públicos más `business` | ✅ |
| `test_cookie_has_priority_over_bearer` | Si llegan ambos, manda la cookie | ✅ |
| `test_without_token` | 401 con `WWW-Authenticate: Bearer` | ✅ |
| `test_garbage_token` | Token basura → 401 | ✅ |
| `test_expired_token` | Token vencido → 401 | ✅ |
| `test_token_signed_with_another_key` | Firma ajena → 401 | ✅ |
| `test_malformed_claims[no-sub / no-role / sub-not-int / unknown-role / no-jti]` | Claims faltantes o inválidos → 401 (5 casos). Cada token lleva todos los demás claims, para que falle solo por el que se prueba | ✅ |
| `test_token_of_deleted_user` | Token de un usuario borrado → 401 | ✅ |
| `test_user_deactivated_after_login` | Desactivado con sesión abierta → 403 en la siguiente petición | ✅ |
| `test_role_comes_from_database_not_from_token` | El rol se lee de la BD: un cambio de rol aplica sin volver a iniciar sesión | ✅ |

**Negocio en `/auth/me` (contrato del frontend, sección 2.1)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_admin_gets_their_business` | El admin recibe `business` con `id`, `name`, `logo_url` y `status` de su negocio | ✅ |
| `test_employee_gets_their_business` | El empleado recibe el negocio al que pertenece | ✅ |
| `test_business_matches_business_id` | `business.id` coincide con `business_id` (negocio B) | ✅ |
| `test_platform_owner_has_no_business` | `platform` recibe `business: null` | ✅ |
| `test_status_and_logo_come_from_the_database` | Estado `trial` y `logo_url` salen de la base | ✅ |
| `test_business_exposes_only_header_fields` | `business` solo trae los 4 campos del encabezado | ✅ |

**Negocio suspendido (H1)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_suspended_business_cannot_login` | Login → 403 `Business suspended`, sin cookie | ✅ |
| `test_suspended_business_message_needs_valid_password` | Con contraseña incorrecta sigue siendo 401: no revela el estado del negocio a quien no sabe la contraseña | ✅ |
| `test_trial_and_active_businesses_can_login[trial / active]` | `trial` y `active` sí entran (2 casos) | ✅ |
| `test_open_session_is_cut_when_business_is_suspended` | Al suspender el negocio, la sesión ya abierta recibe 403 en la siguiente petición | ✅ |
| `test_suspending_a_does_not_affect_b` | Suspender A no afecta a B | ✅ |
| `test_platform_owner_is_not_affected` | El dueño de plataforma (sin negocio) sigue entrando aunque todos estén suspendidos | ✅ |

**Logout (`POST /api/v1/auth/logout`)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_logout_clears_cookie` | 204, cookie con `Max-Age=0` y `/me` → 401 | ✅ |
| `test_logout_without_session` | Sin sesión también responde 204 | ✅ |
| `test_token_copy_is_invalid_after_logout` | Una copia del token (Bearer) ya no sirve después del logout (H2) | ✅ |
| `test_logout_with_bearer_revokes_it` | El logout por Bearer (lector, Swagger) también revoca | ✅ |
| `test_other_sessions_stay_open` | Cerrar sesión en un equipo no cierra la del otro | ✅ |
| `test_logout_twice_is_harmless` | Dos logouts seguidos → 204 y 204 | ✅ |
| `test_logout_with_invalid_token[garbage / bad-parts]` | Token inválido → 204, sin error (2 casos) | ✅ |
| `test_logout_with_expired_token` | Token vencido → 204 | ✅ |
| `test_logging_in_again_after_logout_works` | Después del logout se puede volver a entrar | ✅ |

### 5.5b Límite de intentos de login — `tests/api/test_login_limit.py` (12)

H4: 5 intentos fallidos por email, después 429 durante 15 minutos. Las pruebas de tiempo usan la fixture `clock`, que reemplaza `services.auth_service._now` para avanzar el reloj sin esperar.

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_five_failures_are_allowed_then_429` | 5 fallos → 401; el sexto → 429 | ✅ |
| `test_locked_email_rejects_the_correct_password` | Bloqueado, ni la contraseña correcta entra; sin cookie | ✅ |
| `test_retry_after_header` | El 429 trae `Retry-After` en segundos, ≤ 15 min | ✅ |
| `test_four_failures_do_not_lock` | Con 4 fallos todavía se entra | ✅ |
| `test_successful_login_resets_the_counter` | Un login correcto reinicia el contador | ✅ |
| `test_lock_expires_after_lockout_time` | A los 14 min sigue bloqueado; a los 16 min entra | ✅ |
| `test_after_the_lock_the_user_gets_five_new_attempts` | Pasado el bloqueo hay 5 intentos nuevos | ✅ |
| `test_old_failures_stop_counting` | 4 fallos, 16 min después otros 4: no se bloquea | ✅ |
| `test_lock_is_per_email` | Bloquear a A no afecta a B | ✅ |
| `test_email_case_does_not_bypass_the_lock` | `ADMIN.A@` y `Admin.A@` cuentan como el mismo email | ✅ |
| `test_unknown_email_behaves_the_same` | Un email inexistente recibe los mismos 401 y 429: no se revela qué emails existen | ✅ |
| `test_limit_is_configurable` | Con `login_max_attempts=2`, el tercer intento → 429 | ✅ |

### 5.5c Servicio de autenticación — `tests/unit/test_auth_service.py` (6)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_revoked_token_is_detected` | Un `jti` revocado se detecta | ✅ |
| `test_revoke_is_idempotent` | Revocar dos veces deja una sola fila | ✅ |
| `test_expired_revocations_are_purged` | Se borran las revocaciones ya vencidas y se conservan las vigentes | ✅ |
| `test_logout_purges_old_rows` | Cada logout limpia las revocaciones vencidas | ✅ |
| `test_failed_login_rows_outside_the_window_are_purged` | Se borran los registros de intentos fuera de la ventana | ✅ |
| `test_clear_failed_logins_without_row_is_harmless` | Reiniciar un contador que no existe no falla | ✅ |

### 5.5d Códigos de error estables — `tests/api/test_error_codes.py` (12)

Contrato del frontend, sección 1.2 (DECISIÓN 7). Cada error de negocio trae `code` además de `detail`; el frontend elige el mensaje con `code`. Lo implementa `ApiError` en `core/errors.py`.

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_wrong_password_is_invalid_credentials` | 401 `invalid_credentials` y conserva `WWW-Authenticate` | ✅ |
| `test_unknown_email_is_invalid_credentials` | Email inexistente → mismo `invalid_credentials` | ✅ |
| `test_too_many_attempts_is_login_locked` | Sexto intento → 429 `login_locked` con `Retry-After` | ✅ |
| `test_inactive_user_is_user_inactive` | Usuario inactivo → 403 `user_inactive` | ✅ |
| `test_suspended_business_is_business_suspended` | Login de negocio suspendido → 403 `business_suspended` | ✅ |
| `test_without_session_is_not_authenticated` | Sin sesión → 401 `not_authenticated` | ✅ |
| `test_garbage_token_is_not_authenticated` | Token basura → 401 `not_authenticated` | ✅ |
| `test_revoked_token_is_not_authenticated` | Token revocado por logout → 401 `not_authenticated` | ✅ |
| `test_open_session_of_suspended_business` | Sesión abierta al suspender el negocio → 403 `business_suspended` | ✅ |
| `test_duplicate_email_is_email_taken` | `/user/create` con email repetido → 409 `email_taken` | ✅ |
| `test_field_validation_keeps_fastapi_shape` | Los 422 de validación siguen con `detail` en lista y sin `code` | ✅ |
| `test_errors_outside_the_contract_have_no_code` | Un error fuera de la tabla del contrato (`Permission denied`) no lleva `code` | ✅ |

### 5.6 Usuarios — `tests/api/test_user.py` (53)

**Permisos**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_unauthenticated_requests_are_rejected` | Los 4 endpoints sin token → 401 | ✅ |
| `test_employee_is_forbidden` | `employee` → 403 en los 4 endpoints | ✅ |
| `test_platform_owner_is_forbidden` | `platform` → 403: no administra usuarios de negocios | ✅ |
| `test_admin_without_business_is_rejected` | Admin sin negocio (dato inconsistente) → 403 | ✅ |

**Listar (`GET /user/list`)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_admin_lists_only_own_business` | Solo los 2 usuarios del negocio A | ✅ |
| `test_response_never_exposes_password_hash` | Ningún elemento trae `hashed_password` | ✅ |

**Crear (`POST /user/create`)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_create_defaults_to_employee` | 201, `role=employee`, activo, en el negocio del admin | ✅ |
| `test_create_admin` | Se puede crear otro admin | ✅ |
| `test_created_user_can_login` | El usuario nuevo puede iniciar sesión | ✅ |
| `test_password_is_stored_hashed` | En la BD queda un hash Argon2id, no el texto | ✅ |
| `test_email_is_normalized_to_lowercase` | `New.Person@Demo.MX` → `new.person@demo.mx` | ✅ |
| `test_business_id_in_body_is_ignored` | Mandar `business_id` de B no tiene efecto | ✅ |
| `test_cannot_create_platform_user` | `role=platform` → 403 | ✅ |
| `test_duplicate_email` | Email existente → 409 | ✅ |
| `test_duplicate_email_ignores_case` | `EMPLOYEE.A@demo.mx` también → 409 | ✅ |
| `test_email_is_unique_across_businesses` | Un email de B no se puede usar en A → 409 | ✅ |
| `test_validation_errors[...]` | Email inválido, contraseña < 8 o > 128, nombre vacío o > 120, rol inexistente → 422 (6 casos) | ✅ |
| `test_name_is_normalized` | `"  José   Luis "` se guarda como `"José Luis"` (H5) | ✅ |
| `test_invalid_names_are_rejected[...]` | `"   "`, `"A"`, `"Ana2"`, `"@@@"` → 422 (4 casos, H5) | ✅ |
| `test_required_fields[name / email / password]` | Falta un campo obligatorio → 422 (3 casos) | ✅ |

**Consultar (`GET /user/{user_id}`)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_get_user_of_own_business` | 200 con los datos | ✅ |
| `test_get_nonexistent_user` | 404 `User not found` | ✅ |
| `test_non_numeric_id` | `/user/abc` → 422 | ✅ |

**Editar (`PATCH /user/{user_id}/update`)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_update_name` | Cambia el nombre sin tocar lo demás | ✅ |
| `test_empty_body_changes_nothing` | `{}` deja el usuario igual | ✅ |
| `test_update_password` | La nueva contraseña funciona y la vieja ya no | ✅ |
| `test_update_email` | Cambia y normaliza a minúsculas | ✅ |
| `test_update_email_to_same_value` | Su propio email en otra capitalización → 200, no 409 | ✅ |
| `test_update_email_to_taken_value` | Email de otro usuario → 409 | ✅ |
| `test_deactivate_user_blocks_login` | `is_active=false` → ya no puede iniciar sesión | ✅ |
| `test_role_cannot_be_changed` | Mandar `role` no cambia el rol | ✅ |
| `test_business_cannot_be_changed` | Mandar `business_id` no cambia el negocio | ✅ |
| `test_blank_name_is_rejected_on_update` | Nombre de solo espacios al editar → 422 (H5) | ✅ |
| `test_short_password_is_rejected` | Contraseña corta → 422 | ✅ |
| `test_nonexistent_user` | 404 | ✅ |
| `test_admin_can_update_self` | Un admin puede editar su propio nombre | ✅ |
| `test_admin_cannot_deactivate_self` | `is_active=false` sobre sí mismo → 400, y sigue activo (H3) | ✅ |
| `test_admin_can_send_is_active_true_for_self` | Mandar `is_active=true` sobre sí mismo sí se permite | ✅ |
| `test_admin_can_deactivate_another_admin` | Un admin sí puede desactivar a otro admin de su negocio | ✅ |

**Email duplicado concurrente (H6)**

Reproduce dos peticiones que pasan la revisión de email al mismo tiempo: la fixture desactiva `_ensure_email_available` con `monkeypatch`, así que solo el índice único de `users.email` detiene el duplicado. Sin la corrección, las 4 pruebas fallan con `IntegrityError` (500); se comprobó.

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_create_duplicate_returns_409_not_500` | Crear con un email que la base rechaza → 409 `Email already in use` | ✅ |
| `test_update_to_taken_email_returns_409_not_500` | Editar a un email ocupado → 409 | ✅ |
| `test_failed_update_leaves_user_unchanged` | Si el cambio falla, ni el email ni el nombre se guardan | ✅ |
| `test_api_keeps_working_after_the_conflict` | Tras el `rollback`, la siguiente petición funciona | ✅ |

### 5.6b Niveles — `tests/api/test_tier.py` (40)

Contrato del frontend, sección 4. `GET /tier/list` y `PATCH /tier/{tier_id}/update`; las reglas viven en `services/tier_service.py`. El nivel se paga (`price_cents`), no se alcanza por puntos.

**Listado**
| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_ordered_from_cheapest_to_most_expensive` | Los niveles salen del más barato al más caro aunque se hayan creado en otro orden | ✅ |
| `test_a_price_change_reorders_the_list` | Cambiar un precio cambia el orden | ✅ |
| `test_tiers_have_no_points_threshold` | La respuesta no trae `min_points` | ✅ |
| `test_shape_matches_the_contract` | Campos exactos del contrato, `customers_count` en 0 por ahora | ✅ |
| `test_percents_are_json_numbers` | Los porcentajes son números JSON, no texto | ✅ |
| `test_employee_can_read_the_tiers` | El cajero puede leerlos (la caja muestra los beneficios) | ✅ |
| `test_business_without_tiers_gets_empty_list` | Negocio sin niveles → `[]` | ✅ |
| `test_platform_cannot_read_tiers` | `platform` → 403 | ✅ |
| `test_requires_session` | Sin sesión → 401 `not_authenticated` | ✅ |

**Edición**
| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_updates_every_field` | Cambia los 6 campos y devuelve el nivel actualizado | ✅ |
| `test_change_is_persisted` | El cambio queda en la base | ✅ |
| `test_only_sent_fields_change` | Lo no enviado no cambia | ✅ |
| `test_null_means_not_sent` | `null` no borra el valor | ✅ |
| `test_name_is_trimmed` | Se quitan espacios sobrantes del nombre | ✅ |
| `test_zero_disables_a_benefit` | Los tres beneficios aceptan 0 (= deshabilitado) | ✅ |
| `test_limits_are_accepted` | 100 % es válido | ✅ |
| `test_employee_cannot_update` / `test_platform_cannot_update` | Solo el admin edita → 403 | ✅ |
| `test_unknown_tier_is_404` | Id inexistente → 404 `Tier not found` | ✅ |
| `test_unknown_finish_keeps_fastapi_shape` | `finish` desconocido es validación de campo (422 de FastAPI) | ✅ |

**Rangos** (422 `tier_invalid`, y el nivel no cambia)
| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_out_of_range_is_tier_invalid[...]` | Porcentajes < 0, > 100 o con 3 decimales; `points_per_ten` < 0 o > 1000; `price_cents` < 0 o > 10⁸; nombre vacío o de más de 60 (13 casos) | ✅ |
| `test_price_message_says_the_range` | El error de precio dice el rango permitido | ✅ |
| `test_price_limits_are_accepted` | $0 (nivel gratuito) y $1,000,000.00 son válidos | ✅ |
| `test_two_tiers_can_share_a_price` | Dos niveles pueden costar lo mismo | ✅ |
| `test_out_of_range_is_rejected[...]` | Las restricciones `CHECK` de la base rechazan valores fuera de rango aunque se salte el servicio (4 casos) | ✅ |

### 5.7 Aislamiento multi-negocio — `tests/api/test_isolation.py` (7)

Es la prueba obligatoria del MVP: *"0 filas de otro negocio, comprobado por test automático"*.

```mermaid
sequenceDiagram
    autonumber
    actor AA as Admin A
    participant API
    participant DB

    AA->>API: GET /user/list
    API->>DB: WHERE business_id = A
    DB-->>API: solo usuarios de A
    API-->>AA: 200 — 0 filas de B ✅

    AA->>API: GET /user/{id de B}
    API->>DB: SELECT user
    DB-->>API: user (business_id = B)
    API-->>AA: 404 — igual que si no existiera ✅

    AA->>API: PATCH /user/{id de B}/update
    API-->>AA: 404 — y en la BD no cambió nada ✅

    Note over AA,API: Token falsificado con business_id = B
    AA->>API: GET /user/list (Bearer con business_id de B)
    API->>DB: business_id se toma del usuario en la BD (A)
    API-->>AA: 200 — solo usuarios de A ✅
```

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_admin_a_sees_zero_rows_of_business_b` | El listado de A tiene 0 filas de B | ✅ |
| `test_admin_b_sees_zero_rows_of_business_a` | Y al revés | ✅ |
| `test_get_user_of_other_business_returns_404` | Consultar admin y empleado de B → 404 | ✅ |
| `test_other_business_and_nonexistent_look_identical` | Misma respuesta para "de otro negocio" e "inexistente": no se puede adivinar qué IDs existen | ✅ |
| `test_update_user_of_other_business_is_rejected_and_unchanged` | Intentar cambiar nombre, contraseña y estado de un usuario de B → 404, y en la BD sigue igual | ✅ |
| `test_user_created_by_a_is_invisible_to_b` | Lo que crea A no aparece para B | ✅ |
| `test_forged_business_id_in_token_body_has_no_effect` | Un JWT válido con `business_id` alterado no da acceso: el negocio se toma del usuario en la BD | ✅ |

### 5.7b Aislamiento de niveles — `tests/api/test_isolation_tier.py` (4)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_each_business_sees_only_its_tiers` | El cajero de A ve solo los niveles de A, y el de B solo los de B | ✅ |
| `test_update_tier_of_other_business_is_404_and_unchanged` | Editar un nivel de B desde A → 404, y en la base sigue igual | ✅ |
| `test_other_business_and_nonexistent_look_identical` | Misma respuesta para "de otro negocio" e "inexistente" | ✅ |
| `test_editing_own_tier_leaves_other_business_untouched` | Lo que B edita en sus niveles no toca los de A | ✅ |

### 5.7c Clientes — `tests/api/test_customer.py` (81)

Contrato del frontend, sección 3. Las reglas viven en `services/customer_service.py`. Los casos parametrizados cuentan uno por variante.

| Clase | Qué verifica | Resultado |
|-------|--------------|-----------|
| `TestCreate` | Forma exacta del contrato; código `MP-` + 5 caracteres sin `0/O/1/I/L`; vigencia de 12 meses; fechas en UTC; sin `level_id` entra al nivel más barato; email en minúscula; email repetido → 409 `email_taken` (el mismo email en otro negocio sí se acepta); `level_id` inexistente o negocio sin niveles → 422 `tier_invalid`; validación de nombre, email y teléfono | ✅ |
| `TestStatus` | `active`, por vencer (`expiring_soon`), `expired` y `cancelled` calculados; `cancelled` gana sobre `expired` | ✅ |
| `TestList` | Orden por nombre; forma paginada; 8 por defecto; segunda página; página fuera de rango → la última; negocio vacío → página 1; `page`/`page_size` inválidos → 422; `page_size=500` para la hoja imprimible; búsqueda sin distinguir mayúsculas en nombre, email y código (`%` no es comodín); filtros por estado y nivel, y combinados | ✅ |
| `TestSummary` | Conteos de cada estado, y que coinciden con el `total` del filtro correspondiente de la lista | ✅ |
| `TestLookup` | Normaliza el código (mayúsculas, espacios); código desconocido → 404 `customer_not_found`; responde para vencidas y canceladas; sin `code` → 422 | ✅ |
| `TestDetail` | Ficha del cliente; id desconocido → 404 `customer_not_found` | ✅ |
| `TestUpdate` | Datos personales; cambio de nivel con sus beneficios; `code` y fechas no cambian; `phone: null` lo borra; `null` en campos obligatorios se ignora; email ocupado → 409; conservar el propio email; nivel desconocido → 422; cliente desconocido → 404 | ✅ |
| `TestCancel` | Cancela; es irreversible e idempotente (no cambia `cancelled_at`); cliente desconocido → 404 | ✅ |
| `TestPermissions` | El cajero solo puede usar `lookup` (las otras 6 rutas → 403); `platform` → 403; sin sesión → 401 | ✅ |
| `TestTierCount` | `/tier/list` cuenta solo tarjetas no canceladas | ✅ |
| `TestCodeAndRaces` | Un código ya usado se regenera; tras 10 choques se rinde con error; dos altas con el mismo email a la vez → 409, no 500, y la API sigue respondiendo | ✅ |

### 5.7d Aislamiento de clientes — `tests/api/test_isolation_customer.py` (9)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_list_has_zero_rows_of_the_other_business` | La lista de A tiene 0 filas de B | ✅ |
| `test_search_does_not_reach_the_other_business` | Buscar el nombre o el código de B desde A no encuentra nada | ✅ |
| `test_summary_counts_only_its_business` | Los conteos son solo del propio negocio | ✅ |
| `test_lookup_of_other_business_code_is_404` | El cajero de A no encuentra una tarjeta de B | ✅ |
| `test_detail_of_other_business_looks_like_nonexistent` | Misma respuesta para "de otro negocio" e "inexistente" | ✅ |
| `test_update_and_cancel_of_other_business_are_404_and_unchanged` | Editar o cancelar un cliente de B → 404, y en la base sigue igual | ✅ |
| `test_cannot_assign_a_tier_of_the_other_business` | Un `level_id` de B → 422 al crear y al editar | ✅ |
| `test_level_filter_with_other_business_tier_is_empty` | Filtrar por un nivel de B devuelve 0 | ✅ |
| `test_tier_counts_only_its_customers` | `customers_count` no cuenta clientes de otro negocio | ✅ |

### 5.7e Servicio de clientes — `tests/unit/test_customer_service.py` (10)

`add_months` (mismo día, fin de mes y 29 de febrero), `normalize_code`, y que `generate_code` usa el alfabeto sin caracteres parecidos y produce códigos distintos.

### 5.7f Fórmula de caja — `tests/unit/test_pricing_service.py` (14)

`services/pricing_service.py` sin base de datos: el ejemplo de la rúbrica ($1,000.00 en Oro → 85 000, 85 puntos y $25.50), puntos y cashback sobre la base antes de restar el cashback usado, el cashback usado nunca pasa de la base, redondeo mitad hacia arriba al centavo, puntos hacia abajo por cada $10, tarjeta sin beneficios y nivel con todo en 0.

### 5.7g Caja — `tests/api/test_checkout.py` (35)

Contrato del frontend, sección 5. Los casos parametrizados cuentan uno por variante.

| Clase | Qué verifica | Resultado |
|-------|--------------|-----------|
| `TestCreate` | Forma exacta del comprobante con el ejemplo de la rúbrica; los saldos de `/customer` (ficha, lista y `lookup`) salen de las compras; sin compras, 0 y `null`; usar cashback y su tope en la base; tarjeta vencida o cancelada paga completo y no gana ni usa nada; el admin también cobra; el cajero sale del token | ✅ |
| `TestValidation` | `amount_cents` 0, negativo o mayor a 100 000 000 → 422 `amount_invalid`; no entero → 422 de FastAPI; `concept` se limpia, en blanco es `null`, más de 120 → 422; cliente desconocido → 404 `customer_not_found`; un error no guarda nada | ✅ |
| `TestReceipt` | `GET` devuelve el mismo comprobante; el admin lee todos; un cajero no lee el de otro (404 `checkout_not_found`); id desconocido → 404; el comprobante conserva el nivel aplicado aunque se edite después | ✅ |
| `TestPreview` | Da los mismos números que `create` y no guarda nada; tarjeta vencida; valida igual que `create` | ✅ |
| `TestIdempotency` | La misma clave no cobra dos veces (`Idempotent-Replayed: true`); misma clave con otro monto → 409 `idempotency_conflict`; claves distintas son compras distintas; clave de más de 64 → 422; dos reintentos simultáneos → una sola compra | ✅ |
| `TestPermissions` | `platform` → 403; sin sesión → 401 | ✅ |

### 5.7h Aislamiento de caja — `tests/api/test_isolation_checkout.py` (4)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_cannot_charge_a_customer_of_the_other_business` | Cobrar o previsualizar a un cliente de B desde A → 404, y no se guarda nada | ✅ |
| `test_receipt_of_the_other_business_looks_like_nonexistent` | El comprobante de B responde igual que uno inexistente | ✅ |
| `test_balances_count_zero_rows_of_the_other_business` | Los saldos de A no suman compras de B | ✅ |
| `test_idempotency_keys_are_per_business` | La misma `Idempotency-Key` en dos negocios son dos compras | ✅ |

### 5.7i Movimientos — `tests/api/test_movement.py` (41)

Contrato del frontend, sección 6. Las compras se registran con `/checkout/create` y después se mueven en el tiempo. Los casos parametrizados cuentan uno por variante.

| Clase | Qué verifica | Resultado |
|-------|--------------|-----------|
| `TestList` | Forma exacta del movimiento (`cashier_name`, `points_delta`, sin `register_name`); su id es el del comprobante; más reciente primero; `summary` suma todo el conjunto filtrado aunque la página sea de 1; sin compras todo en 0; filtro por cliente; `q` por nombre o código sin distinguir mayúsculas, no por correo; `from`/`to` inclusivos y sin zona = UTC; "últimos 7 días"; página fuera de rango → la última; cliente desconocido → lista vacía; parámetros inválidos → 422 | ✅ |
| `TestExport` | `text/csv; charset=utf-8`, `attachment` con nombre `movimientos-AAAAMMDD.csv` y BOM; columnas en orden e importes en pesos (`1000.00`, `25.50`); mismos filtros que `list` sin paginar; sin compras solo el encabezado; una celda que empieza con `=` sale con `'` | ✅ |
| `TestHelpers` | `pesos` (0, centavos sueltos, negativos) y `safe_cell` (`=`, `+`, `-`, `@`, vacío) | ✅ |
| `TestPermissions` | `employee` y `platform` → 403 en las dos rutas; sin sesión → 401 | ✅ |

### 5.7j Aislamiento de movimientos — `tests/api/test_isolation_movement.py` (3)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_list_shows_zero_rows_of_the_other_business` | La lista y su `summary` de A no cuentan compras de B | ✅ |
| `test_filtering_by_a_customer_of_the_other_business_finds_nothing` | `customer_id` o `q` de un cliente de B → lista vacía | ✅ |
| `test_export_has_zero_rows_of_the_other_business` | El CSV de A no trae filas de B, ni filtrando por su cliente | ✅ |

### 5.7k Plataforma — `tests/api/test_platform.py` (19)

Contrato del frontend, sección 7. No usa `BusinessId`, así que no lleva prueba de aislamiento entre negocios. En su lugar, `TestPrivacy` comprueba que no sale ningún dato de clientes.

| Clase | Qué verifica | Resultado |
|-------|--------------|-----------|
| `TestList` | Forma exacta del negocio; todos los negocios por nombre; `customers_count` no cuenta tarjetas canceladas; filtro por `status`; `q` busca en el nombre sin distinguir mayúsculas y no en los clientes; página fuera de rango → la última; parámetros inválidos → 422 | ✅ |
| `TestPrivacy` | La respuesta no trae nombres, códigos, correos, puntos ni cashback de clientes; solo las 5 llaves del contrato | ✅ |
| `TestPermissions` | `admin` y `employee` → 403; sin sesión → 401 | ✅ |

### 5.7l Entrega de la tarjeta digital — `tests/api/test_card.py` (59)

Contrato del frontend, sección 13 (enlace, correo, tarjeta pública y Google Wallet). Las rutas `/card` no usan sesión. El correo se prueba sin mocks: sin `SMTP_HOST` va a la bandeja en memoria (`email_service.OUTBOX`), y `tests/smtp_server.py` levanta un servidor SMTP real en `127.0.0.1` que acepta, rechaza o tarda.

| Clase | Qué verifica | Resultado |
|-------|--------------|-----------|
| `TestCreateLink` | La URL es `{FRONTEND_PUBLIC_URL}/tarjeta/<token>` con un token de 43 caracteres y `expires_at` = `valid_until`; en la base solo queda el SHA-256 del token; los tokens son aleatorios y no contienen el código; un enlace nuevo revoca el anterior y queda uno activo; tarjeta cancelada → 409 `customer_cancelled`; vencida → 409 `customer_expired`; cliente inexistente → 404 `customer_not_found` | ✅ |
| `TestSendLink` | Envía al correo del cliente con asunto `Tu tarjeta de {negocio}` y remitente con el nombre del negocio; el cuerpo sigue el contrato y no lleva código, puntos, saldo ni signos de exclamación; el enlace del correo abre la tarjeta; cada correo lleva un enlace nuevo y revoca el copiado; otro envío antes de 1 minuto → 429 `card_email_rate_limited` con `Retry-After` y sin revocar el enlace; 5 envíos en la última hora → 429 (4 sí pasan; los de hace más de una hora no cuentan); tarjeta cancelada o vencida → 409; cliente inexistente → 404 | ✅ |
| `TestSmtp` | Envía por SMTP real; el proveedor que cierra la conexión → 502 `email_failed`; en producción sin `SMTP_HOST` → 502 | ✅ |
| `TestCreateCustomer` | El alta envía la tarjeta por defecto (`card_email.status` = `sent`) y el enlace abre; `send_card_email: false` → `skipped` y sin enlace; un correo fallido no falla el alta (`failed`, 201); un proveedor lento → `pending` sin pasar del plazo; el alta cuenta para el límite de envíos | ✅ |
| `TestPublicCard` | Forma exacta del contrato (sin sesión); no trae correo, teléfono, puntos, cashback ni ids; `Cache-Control: no-store` en 200 y en 404; token desconocido, largo o revocado → mismo 404 `card_link_not_found`; cancelar revoca el enlace; tarjeta vencida o negocio suspendido → mismo 404; tarjeta renovada vuelve a abrir; más de `CARD_RATE_LIMIT_PER_MINUTE` por IP → 429 `rate_limited` con `Retry-After` | ✅ |
| `TestGoogleWallet` | Sin configuración → 503 `wallet_unavailable` con `no-store`; token desconocido → 404 antes que el 503; tarjeta cancelada → 404; con configuración la tarjeta dice `wallet.google = true`; el JWT se firma con RS256 y se decodifica con la llave pública de prueba (`iss`, `aud`, `typ`, `origins`); lleva la clase del negocio y el objeto del cliente con el QR igual al `code`; usa el logo `https` del negocio si existe; una cuenta de servicio rota o una variable vacía → sin configurar | ✅ |
| `TestPermissions` | `card-link` y `card-link/send`: `employee` y `platform` → 403; sin sesión → 401. La tarjeta pública abre sin sesión | ✅ |

### 5.7m Aislamiento del enlace — `tests/api/test_isolation_card.py` (3)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_admin_b_gets_404_for_a_customer_of_a` | El admin de B no puede crear ni enviar el enlace de un cliente de A (404); no se guarda nada ni sale ningún correo | ✅ |
| `test_a_link_of_a_shows_only_a` | El enlace de A muestra el negocio A aunque lo abra una sesión de B | ✅ |

### 5.7n Límite por IP — `tests/unit/test_rate_limit.py` (5)

`core/rate_limit.py`: ventana deslizante en memoria. Permite hasta el límite y luego da los segundos de espera; cuenta cada llave aparte; las peticiones viejas salen de la ventana; `reset` borra todo; con demasiadas llaves descarta las que ya no tienen peticiones.

### 5.8 Hallazgos conocidos — `tests/api/test_known_issues.py` (0)

Hoy no hay hallazgos abiertos. El archivo se conserva vacío para registrar los siguientes como `xfail(strict=True)`.

Los 5 que pasaron por aquí (H1–H5) se corrigieron. Al corregir cada uno, `strict=True` hizo fallar su prueba (`XPASS(strict)`), como estaba previsto, y se movió a la suite normal con más casos:

| Hallazgo | Ahora en |
|----------|----------|
| H1 | `test_auth.py` → `TestBusinessStatus` |
| H2 | `test_auth.py` → `TestLogout` |
| H3 | `test_user.py` → `TestUpdateUser` |
| H4 | `test_login_limit.py` |
| H5 | `test_validators.py` y `test_user.py` |

### 5.9 Migraciones — `tests/db/test_migrations.py` (9)

Usan su propia fixture `empty_database`, que deja la base sin ninguna tabla (ni `alembic_version`) y ejecutan Alembic con una conexión abierta. Detalle en [MIGRATIONS.md](MIGRATIONS.md#8-pruebas-de-las-migraciones).

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_there_is_a_single_head` | Una sola cabeza: no hay migraciones paralelas sin fusionar | ✅ |
| `test_upgrade_creates_all_tables` | `upgrade head` crea todas las tablas (`businesses`, `users`, `revoked_tokens`, `login_attempts`, `tiers`) y `alembic_version` | ✅ |
| `test_models_and_migrations_are_in_sync` | Los modelos y las migraciones coinciden (detecta migraciones olvidadas) | ✅ |
| `test_downgrade_removes_tables_and_enums` | `downgrade base` borra tablas y, en PostgreSQL, los tipos `ENUM` | ✅ |
| `test_upgrade_after_downgrade` | Se puede bajar y volver a subir | ✅ |
| `test_database_is_stamped_at_head` | `alembic_version` queda en la última revisión | ✅ |
| `test_app_works_on_migrated_schema` | Login y alta de usuario sobre tablas creadas por Alembic | ✅ |
| `test_lowercase_enum_migration_converts_existing_rows` | Filas con `'ADMIN'`/`'SUSPENDED'` de la primera migración quedan en `'admin'`/`'suspended'`, y el `downgrade` las regresa (H7) | ✅ |
| `test_app_stores_lowercase_enum_values` | La app guarda `'employee'` y `'trial'` en la base (H7) | ✅ |

Para comprobar que la prueba de sincronía sirve, se agregó temporalmente `phone: str | None` a `User` sin generar migración. La prueba falló como se esperaba:

```text
Differences: [('add_column', None, 'users', Column('phone', AutoString(), table=<users>))]
```

---

### 5.10 Seed de demo — `tests/scripts/test_seed.py` (48)

`scripts/seed.py` crea Café Aurora y Gimnasio Titán (`active`) con 4 usuarios (dueño de plataforma, admin y empleado de Café Aurora, y admin de Gimnasio Titán) y sus niveles: Bronce, Plata, Oro y Onyx en Café Aurora (beneficios del contrato, sección 8; precios de demo de $0, $199, $399 y $699) y Básico y Premium en Gimnasio Titán, distintos a propósito.

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_creates_two_active_businesses` | Los dos negocios, en estado `active` | ✅ |
| `test_creates_the_demo_users_with_their_roles` | Los 4 usuarios con su rol | ✅ |
| `test_users_belong_to_the_right_business` | Cada usuario en su negocio; el dueño sin negocio | ✅ |
| `test_passwords_are_hashed` | Contraseñas en Argon2id y verificables | ✅ |
| `test_demo_names_follow_the_name_rule[...]` | Los nombres de demo cumplen `PersonName` (4 casos) | ✅ |
| `test_cafe_aurora_gets_the_contract_tiers` | Café Aurora tiene los 4 niveles del contrato, vistos desde `/tier/list` | ✅ |
| `test_gimnasio_titan_gets_different_tiers` | Gimnasio Titán tiene Básico y Premium | ✅ |
| `test_a_better_tier_costs_more` | En cada negocio, el nivel más caro da igual o más descuento | ✅ |
| `test_an_edited_tier_is_not_overwritten` | Volver a correr el seed no pisa un nivel editado | ✅ |
| `test_cafe_aurora_has_twelve_customers_in_every_state` | Café Aurora tiene 12 clientes: activos, 2 por vencer, 1 vencido y 1 cancelado | ✅ |
| `test_gimnasio_titan_has_its_own_customers` | Gimnasio Titán tiene sus 2 clientes | ✅ |
| `test_the_contract_card_is_found_at_the_counter` | `MP-4F7K2` (Laura Méndez, Oro) se encuentra en caja | ✅ |
| `test_tiers_count_the_seeded_customers` | `customers_count` de cada nivel coincide con el seed (sin la cancelada) | ✅ |
| `test_demo_customers_follow_the_rules[...]` | Nombres válidos y códigos sin caracteres parecidos (14 casos) | ✅ |
| `test_balances_follow_the_checkout_formula` | Laura Méndez: $1,000 en Oro y luego $250 usando su cashback → 106 puntos y $6.38 | ✅ |
| `test_purchase_after_expiry_earned_nothing` | Ricardo Flores compra con la tarjeta activa y otra vez ya vencida: la segunda no gana nada | ✅ |
| `test_gimnasio_titan_has_its_own_purchase` | Gimnasio Titán tiene su propia compra y saldos | ✅ |
| `test_second_run_creates_nothing` | Correrlo dos veces no duplica nada (39 registros) | ✅ |
| `test_existing_password_is_never_changed` | Una segunda corrida con otra contraseña no cambia la existente | ✅ |
| `test_completes_partial_data` | Si ya existe un negocio, crea solo lo que falta | ✅ |
| `test_admin_a_sees_only_cafe_aurora` | El admin de Café Aurora ve solo a sus 2 usuarios | ✅ |
| `test_admin_b_sees_nothing_of_a` | El admin de Gimnasio Titán no ve nada de Café Aurora | ✅ |
| `test_every_demo_user_can_log_in` | Los 4 usuarios inician sesión con su rol | ✅ |
| `test_development_uses_the_demo_password` | En desarrollo sin `SEED_PASSWORD` usa `demo12345` | ✅ |
| `test_seed_password_wins` | `SEED_PASSWORD` tiene prioridad | ✅ |
| `test_production_requires_seed_password` | En producción sin `SEED_PASSWORD` → error | ✅ |
| `test_short_seed_password_is_rejected` | Menos de 8 caracteres → error | ✅ |
| `test_main_seeds_and_prints` | El comando imprime lo creado y la contraseña de demo | ✅ |
| `test_main_reports_existing_data` | En la segunda corrida reporta "exists" y no crea nada | ✅ |
| `test_main_never_prints_a_custom_password` | Una `SEED_PASSWORD` propia nunca se imprime | ✅ |
| `test_main_fails_without_password_in_production` | Sale con código 1 y mensaje "Seed aborted" | ✅ |
| `test_the_printed_link_opens_the_demo_card` | El enlace que imprime el seed abre la tarjeta `MP-4F7K2` de Café Aurora; la segunda corrida no crea otro | ✅ |

También se probó dentro de la imagen Docker: crea los datos con `SEED_PASSWORD` y se niega a correr sin ella en producción.

---

### 5.11 Reglas de convención — `tests/rules/` (12)

No prueban comportamiento: **leen el código fuente** (AST) y el árbol de archivos, y fallan cuando un módulo nuevo rompe una regla de `AGENTS.md` o contradice `ARCHITECTURE.md`. Las pruebas de los puntos 5.1–5.10 solo cubren lo que ya existe; estas atajan lo que alguien está por agregar mal.

No usan fixtures ni base de datos, así que corren también en el job de PostgreSQL sin costo. Están dentro de `tests/`, de modo que `ci.yml` las recoge sin cambios: son parte de `pytest`.

| Prueba | Verifica | Regla |
|--------|----------|-------|
| `test_input_schemas_never_accept_business_id` | Ningún `*Create` / `*Update` declara `business_id` | `business_id` sale del token |
| `test_output_schemas_never_expose_credentials` | Ningún `*Response` expone `hashed_password`, `password`, `secret`, `api_key`… | Los DTO de salida no filtran credenciales |
| `test_every_module_has_an_output_schema` | Existe al menos un `*Response` en `schemas/` | Un módulo declara lo que devuelve |
| `test_no_async_functions_in_the_application` | No hay `async def` en `api/`, `core/`, `db/`, `models/`, `schemas/`, `scripts/`, `services/` | El proyecto es síncrono |
| `test_every_route_matches_the_resource_action_shape` | Toda ruta es `/<recurso>/<acción>`, con la acción en lista cerrada; `SUB_RESOURCES` permite `business` en `/platform/business/list` | Convención de rutas |
| `test_only_health_lives_outside_the_version_prefix` | Solo `/health` vive fuera de `/api/v1` | Todo lo demás va versionado |
| `test_every_router_module_is_registered_in_main` | Todo `api/v1/*_api.py` está en `API_V1_ROUTERS` | Un router sin registrar es código muerto |
| `test_every_registered_router_comes_from_a_module` | Todo router registrado tiene su módulo | Sin routers fantasma en `main.py` |
| `test_every_business_scoped_router_has_an_isolation_test` | Todo router que usa `BusinessId` aparece en `tests/api/test_isolation*.py` | Criterio del MVP: 0 filas de otro negocio |
| `test_every_model_table_is_in_the_er_diagram` | Toda tabla de `models/` está en el `erDiagram` de `ARCHITECTURE.md` | Doc actualizado en el mismo commit |
| `test_every_documented_table_exists_in_the_models` | Ninguna tabla documentada sobra | El diagrama no miente |
| `test_every_route_is_documented` | Toda ruta de la app aparece en la tabla de endpoints | Doc actualizado en el mismo commit |

`main.py` queda fuera de la regla de `async` a propósito: FastAPI exige `async def lifespan`. Las rutas se leen del esquema de OpenAPI y no de `app.routes`, porque la versión instalada de FastAPI envuelve los routers incluidos y sus rutas no aparecen en esa lista.

#### Comprobación de que sí fallan

A una prueba que nunca falla no se le puede creer nada. Se inyectó una violación de cada tipo, se corrió la suite, se comprobó que **esa** prueba fallara y se restauró el archivo verificando que quedara idéntico:

| Violación inyectada | Prueba que falló |
|---------------------|------------------|
| `business_id` agregado a `UserUpdate` | `test_input_schemas_never_accept_business_id` |
| `customer_api.py` creado sin registrarlo en `main.py` | `test_every_router_module_is_registered_in_main` |
| `async def ping()` al final de `db/database.py` | `test_no_async_functions_in_the_application` |
| Ruta `/user/getAll` en lugar de `/user/list` | `test_every_route_matches_the_resource_action_shape` |
| `login_attempts` renombrada a `login_attemptz` en el `erDiagram` | `test_every_model_table_is_in_the_er_diagram` |

---

## 6. Resultados de la ejecución

Ejecutado el 12 de noviembre de 2026. Conteos y tiempos vueltos a medir al agregar las pruebas de reglas (sección 5.11): 217 + 12 = 229. Se corrieron en el homeserver (Ubuntu, Intel i5-8500), más lento que la laptop de la tabla de entorno, así que los tiempos no son comparables con corridas anteriores.

### Entorno

| Componente | Versión |
|------------|---------|
| Sistema | Arch Linux, kernel 7.2.15 |
| Python | 3.14.10 |
| uv | 0.13.7 |
| FastAPI | 0.162.4 |
| SQLModel | 0.0.48 |
| psycopg | 3.3.8 |
| pytest | 9.2.0 |
| Alembic | 1.20.1 |
| PostgreSQL | 18.6 (imagen `postgres:18` de Docker) |

### SQLite

```text
$ uv run pytest -q
........................................................................ [ 94%]
.............                                                            [100%]
229 passed in 85.38s (0:01:25)
```

### PostgreSQL 18.6

```text
$ TEST_DATABASE_URL=postgresql+psycopg://...@localhost:5433/memberplus_test uv run pytest -q
........................................................................ [ 94%]
.............                                                            [100%]
229 passed in 32.97s
```

Se ejecutó dos veces seguidas con el mismo resultado: las pruebas no dependen del orden ni dejan datos.

### Cobertura

```text
$ uv run pytest --cov
Name                            Stmts   Miss Branch BrPart  Cover
-----------------------------------------------------------------
api/v1/auth_api.py                 42      0      6      0   100%
api/v1/dependencies.py             55      0     16      0   100%
api/v1/user_api.py                 55      0     16      0   100%
core/config.py                     31      0      2      0   100%
core/cors.py                        5      0      0      0   100%
core/security.py                   17      0      0      0   100%
db/database.py                     13      0      0      0   100%
main.py                            22      0      2      0   100%
models/__init__.py                  5      0      0      0   100%
models/business_model.py           16      0      0      0   100%
models/enum_utils.py                3      0      0      0   100%
models/login_attempt_model.py       8      0      0      0   100%
models/revoked_token_model.py       7      0      0      0   100%
models/user_model.py               18      0      0      0   100%
schemas/token_schema.py             5      0      0      0   100%
schemas/user_schema.py             14      0      0      0   100%
schemas/validators.py              13      0      4      0   100%
scripts/seed.py                    62      0     20      0   100%
services/auth_service.py           44      0     12      0   100%
-----------------------------------------------------------------
TOTAL                             435      0     78      0   100%
```

El MVP pide ≥ 60 % de cobertura en `services/`. Hoy `services/auth_service.py` está al 100 %; la lógica de caja (hito H2) entrará en la misma carpeta.

### Pruebas más lentas

```text
0.54s  test_successful_login_resets_the_counter
0.53s  test_after_the_lock_the_user_gets_five_new_attempts
0.49s  test_old_failures_stop_counting
0.33s  test_lock_expires_after_lockout_time
0.32s  test_lock_is_per_email
```

Son las del límite de login: cada una hace entre 5 y 10 logins, y cada login verifica Argon2id.

Lo lento es Argon2id, que está hecho para ser costoso: verificar una contraseña tarda ~66 ms en promedio (medido con 20 verificaciones). Queda muy por debajo del criterio del MVP (login → panel en ≤ 2 s).

---

## 7. Hallazgos

Problemas encontrados durante las pruebas. Las decisiones de cómo resolverlos se tomaron con el equipo el 12 de noviembre de 2026 y están registradas en la wiki (*Decisiones por validar*). **Los 7 están corregidos.**

| ID | Hallazgo | Severidad | Estado | Cómo quedó |
|----|----------|-----------|--------|------------|
| H1 | Un usuario de un negocio **suspendido** podía iniciar sesión y operar | Alta | ✅ Corregido | `ensure_user_can_access()` en `api/v1/dependencies.py` responde 403 `Business suspended` en el login **y** en cada petición, así que suspender corta también las sesiones abiertas. `trial` y `active` entran; el dueño de plataforma no se ve afectado |
| H2 | **Logout no invalidaba el token**: solo borraba la cookie. Una copia del JWT (Bearer) seguía sirviendo hasta que expirara (8 h) | Media | ✅ Corregido | Cada token lleva un `jti` único; el logout lo guarda en `revoked_tokens` y cada petición lo revisa → 401. Solo se cierra esa sesión; las de otros equipos siguen abiertas. Las filas se purgan cuando el token habría expirado |
| H3 | Un admin podía **desactivarse a sí mismo** y dejar al negocio sin administrador | Media | ✅ Corregido | `/user/{id}/update` responde 400 `You cannot deactivate your own account`. Un admin sí puede desactivar a otro admin |
| H4 | **Sin límite de intentos** de login: permitía fuerza bruta | Media | ✅ Corregido | 5 intentos fallidos por email; después 429 con `Retry-After` durante 15 min, aunque la contraseña sea correcta. Tabla `login_attempts`; configurable con `LOGIN_MAX_ATTEMPTS` y `LOGIN_LOCKOUT_MINUTES`. Cuenta igual para emails inexistentes |
| H5 | Un **nombre de solo espacios** (`"   "`) pasaba la validación | Baja | ✅ Corregido | Tipo `PersonName` en `schemas/validators.py`: normaliza espacios, solo letras, espacios, guion y apóstrofo, **mínimo 2 letras** (se descartó "mínimo 5" porque rechaza nombres reales como Ana, Luis o Iván) |
| H6 | Si dos peticiones creaban el **mismo email al mismo tiempo**, la segunda fallaba en la base con `IntegrityError` → **500** | Baja | ✅ Corregido | `_save()` en `api/v1/user_api.py` captura `IntegrityError`, hace `rollback` y responde 409. Probado reproduciendo la carrera con `monkeypatch` |
| H7 | Los `ENUM` se guardaban con el **nombre** del miembro (`'ADMIN'`) y la API usa el **valor** (`"admin"`) | Baja | ✅ Corregido | Los modelos guardan el valor (`values_callable`, `models/enum_utils.py`) y la migración `c9e2d3e6ee70` convierte las etiquetas y los datos existentes a minúscula |

### Ciclo de vida de un hallazgo

```mermaid
stateDiagram-v2
    [*] --> Detectado: se encuentra al probar
    Detectado --> Documentado: prueba xfail strict y fila en esta tabla
    Documentado --> Corregido: se arregla el código
    Corregido --> XPASS: la prueba pasa y strict la marca como falla
    XPASS --> Cerrado: se quita el xfail y pasa a la suite normal
    Cerrado --> [*]
```

---

## 8. Cómo agregar pruebas

Para cada módulo nuevo (clientes, membresías, niveles, caja…) se crea `tests/api/test_<modulo>.py` siguiendo el mismo patrón:

```python
from fastapi.testclient import TestClient

from tests.conftest import login

BASE = "/api/v1/customer"


def test_admin_creates_customer(client: TestClient, two_businesses) -> None:
    login(client, "admin.a@demo.mx")
    response = client.post(f"{BASE}/create", json={"name": "Ana"})
    assert response.status_code == 201
    assert response.json()["business_id"] == two_businesses["business_a"].id
```

### Lista mínima por módulo

- [ ] Camino feliz de cada endpoint.
- [ ] Sin token → 401 en todos los endpoints.
- [ ] Roles sin permiso → 403.
- [ ] Validaciones del schema → 422.
- [ ] **Aislamiento:** el negocio A ve 0 filas de B, y consultar o editar un recurso de B → 404.
- [ ] Mandar `business_id` en el cuerpo no tiene efecto.
- [ ] La respuesta no expone campos sensibles.
- [ ] Si cambió un modelo: migración generada y `test_models_and_migrations_are_in_sync` en verde.
- [ ] Corre en SQLite **y** en PostgreSQL.
- [ ] Actualizar las tablas de la [sección 5](#5-casos-de-prueba) y los resultados de la [sección 6](#6-resultados-de-la-ejecución).

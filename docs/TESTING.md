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
| Fecha de ejecución | 11 de noviembre de 2026 |
| Pruebas | **124** (119 pasan + 5 `xfail` esperados) |
| Fallas | **0** |
| Cobertura de líneas y ramas | **100 %** (254 sentencias, 32 ramas) |
| Bases de datos probadas | SQLite y **PostgreSQL 18.6** |
| Tiempo | ~8 s en SQLite · ~23 s en PostgreSQL |
| Criterio del MVP "0 filas de otro negocio" | ✅ Cumplido (7 pruebas de aislamiento) |
| Migraciones (Alembic) | ✅ Suben, bajan y coinciden con los modelos (7 pruebas) |

Los 5 `xfail` no son fallas: son [hallazgos](#7-hallazgos) documentados como pruebas del comportamiento deseado, que hoy fallan a propósito.

```mermaid
pie showData
    title Pruebas por archivo (124)
    "test_user.py" : 40
    "test_auth.py" : 30
    "test_security.py" : 16
    "test_system.py" : 8
    "test_isolation.py" : 7
    "test_migrations.py" : 7
    "test_config.py" : 7
    "test_known_issues.py" : 5
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

---

## 3. Estrategia

### Niveles

```mermaid
flowchart TB
    subgraph UNIT["Unitarias — tests/unit/ (27)"]
        U1["test_security.py<br/>Argon2id y JWT"]
        U2["test_config.py<br/>Settings y .env"]
        U3["test_models.py<br/>defaults y restricciones"]
    end

    subgraph API["De API / integración — tests/api/ (90)"]
        A1["test_system.py<br/>/health · OpenAPI · CORS"]
        A2["test_auth.py<br/>login · sesión · tokens"]
        A3["test_user.py<br/>/user: permisos y reglas"]
        A4["test_isolation.py<br/>aislamiento multi-negocio"]
        A5["test_known_issues.py<br/>hallazgos (xfail)"]
    end

    subgraph DBT["De base de datos — tests/db/ (7)"]
        D1["test_migrations.py<br/>Alembic: upgrade · downgrade · sincronía"]
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
| Validación | Email inválido, contraseña corta o nombre vacío → 422 |
| Reglas de negocio | Email único, `business_id` del token, rol no editable |
| Seguridad de la respuesta | Nunca aparece `hashed_password` |
| Efecto real | Después de cambiar la contraseña, la vieja ya no sirve |

### Códigos de respuesta esperados

```mermaid
flowchart TD
    REQ["Petición a /api/v1/user/*"] --> T{"¿Hay token en<br/>cookie o Bearer?"}
    T -- no --> E401a["401"]
    T -- sí --> V{"¿JWT válido, firmado<br/>y sin expirar?"}
    V -- no --> E401b["401"]
    V -- sí --> U{"¿El usuario existe?"}
    U -- no --> E401c["401"]
    U -- sí --> ACT{"¿is_active?"}
    ACT -- no --> E403a["403 Inactive user"]
    ACT -- sí --> R{"¿role = admin?<br/>(rol leído de la BD)"}
    R -- no --> E403b["403 Permission denied"]
    R -- sí --> B{"¿Tiene business_id?"}
    B -- no --> E403c["403 does not belong to a business"]
    B -- sí --> BODY{"¿Cuerpo válido?"}
    BODY -- no --> E422["422"]
    BODY -- sí --> OWN{"¿El recurso es<br/>de su negocio?"}
    OWN -- no --> E404["404 User not found"]
    OWN -- sí --> OK["200 / 201"]
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
│   └── test_models.py
└── api/
    ├── test_system.py
    ├── test_auth.py
    ├── test_user.py
    ├── test_isolation.py
    └── test_known_issues.py
└── db/
    └── test_migrations.py
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

### 5.1 Seguridad — `tests/unit/test_security.py` (16)

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
| `test_token_contains_expected_claims` | `sub`, `role`, `business_id` y `exp` | ✅ |
| `test_platform_token_has_null_business` | `business_id = null` para `platform` | ✅ |
| `test_default_expiration_matches_settings` | Expira en 480 min | ✅ |
| `test_custom_expiration` | Respeta `expires_delta` | ✅ |
| `test_expired_token_is_rejected` | Token vencido → `ExpiredSignatureError` | ✅ |
| `test_tampered_token_is_rejected` | Payload alterado (empleado → admin) → firma inválida | ✅ |
| `test_token_signed_with_another_key_is_rejected` | Firmado con otra clave → rechazado | ✅ |
| `test_unsigned_token_alg_none_is_rejected` | Ataque `alg: none` → rechazado | ✅ |
| `test_garbage_token_is_rejected` | Texto que no es JWT → rechazado | ✅ |

### 5.2 Configuración — `tests/unit/test_config.py` (7)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_secret_key_is_required` | Sin `SECRET_KEY` la app no arranca | ✅ |
| `test_empty_database_url_falls_back_to_sqlite` | `DATABASE_URL` vacío → `sqlite:///memberplus.db` | ✅ |
| `test_database_url_is_used_when_present` | Usa la URL de Postgres si existe | ✅ |
| `test_cors_origins_are_split_by_comma` | `"a, b ,"` → `["a", "b"]` | ✅ |
| `test_cors_origins_accept_a_list` | También acepta una lista | ✅ |
| `test_defaults` | HS256, 480 min, cookie `access_token`, `secure=false`, `development` | ✅ |
| `test_invalid_environment_is_rejected` | `ENVIRONMENT=staging` → error | ✅ |

### 5.3 Modelos — `tests/unit/test_models.py` (4)

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_business_defaults` | Negocio nuevo: `status=trial`, `logo_url=null`, `created_at` | ✅ |
| `test_user_defaults` | Usuario nuevo: `role=employee`, `is_active=true` | ✅ |
| `test_email_unique_constraint` | La base rechaza emails duplicados (`IntegrityError`) | ✅ |
| `test_enum_values` | Valores exactos de `Role` y `BusinessStatus` | ✅ |

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

### 5.5 Autenticación — `tests/api/test_auth.py` (30)

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
| `test_me_never_exposes_password_hash` | Solo devuelve los 7 campos públicos | ✅ |
| `test_cookie_has_priority_over_bearer` | Si llegan ambos, manda la cookie | ✅ |
| `test_without_token` | 401 con `WWW-Authenticate: Bearer` | ✅ |
| `test_garbage_token` | Token basura → 401 | ✅ |
| `test_expired_token` | Token vencido → 401 | ✅ |
| `test_token_signed_with_another_key` | Firma ajena → 401 | ✅ |
| `test_malformed_claims[no-sub / no-role / sub-not-int / unknown-role]` | Claims faltantes o inválidos → 401 (4 casos) | ✅ |
| `test_token_of_deleted_user` | Token de un usuario borrado → 401 | ✅ |
| `test_user_deactivated_after_login` | Desactivado con sesión abierta → 403 en la siguiente petición | ✅ |
| `test_role_comes_from_database_not_from_token` | El rol se lee de la BD: un cambio de rol aplica sin volver a iniciar sesión | ✅ |

**Logout (`POST /api/v1/auth/logout`)**

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_logout_clears_cookie` | 204, cookie con `Max-Age=0` y `/me` → 401 | ✅ |
| `test_logout_without_session` | Sin sesión también responde 204 | ✅ |

### 5.6 Usuarios — `tests/api/test_user.py` (40)

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
| `test_short_password_is_rejected` | Contraseña corta → 422 | ✅ |
| `test_nonexistent_user` | 404 | ✅ |
| `test_admin_can_update_self` | Un admin puede editar su propio nombre | ✅ |

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

### 5.8 Hallazgos conocidos — `tests/api/test_known_issues.py` (5)

Cada una describe el comportamiento **deseado** y hoy falla a propósito. Detalle en la [sección 7](#7-hallazgos).

| Prueba | Comportamiento deseado | Resultado |
|--------|------------------------|-----------|
| `test_h1_suspended_business_cannot_login` | Un negocio suspendido no puede iniciar sesión | ⚠️ xfail |
| `test_h2_token_is_invalid_after_logout` | El token deja de servir al cerrar sesión | ⚠️ xfail |
| `test_h3_admin_cannot_deactivate_self` | Un admin no puede desactivarse a sí mismo | ⚠️ xfail |
| `test_h4_repeated_failed_logins_are_throttled` | Tras 10 intentos fallidos → 429 | ⚠️ xfail |
| `test_h5_blank_name_is_rejected` | Un nombre de solo espacios → 422 | ⚠️ xfail |

### 5.9 Migraciones — `tests/db/test_migrations.py` (7)

Usan su propia fixture `empty_database`, que deja la base sin ninguna tabla (ni `alembic_version`) y ejecutan Alembic con una conexión abierta. Detalle en [MIGRATIONS.md](MIGRATIONS.md#8-pruebas-de-las-migraciones).

| Prueba | Verifica | Resultado |
|--------|----------|-----------|
| `test_there_is_a_single_head` | Una sola cabeza: no hay migraciones paralelas sin fusionar | ✅ |
| `test_upgrade_creates_all_tables` | `upgrade head` crea `businesses`, `users` y `alembic_version` | ✅ |
| `test_models_and_migrations_are_in_sync` | Los modelos y las migraciones coinciden (detecta migraciones olvidadas) | ✅ |
| `test_downgrade_removes_tables_and_enums` | `downgrade base` borra tablas y, en PostgreSQL, los tipos `ENUM` | ✅ |
| `test_upgrade_after_downgrade` | Se puede bajar y volver a subir | ✅ |
| `test_database_is_stamped_at_head` | `alembic_version` queda en la última revisión | ✅ |
| `test_app_works_on_migrated_schema` | Login y alta de usuario sobre tablas creadas por Alembic | ✅ |

Para comprobar que la prueba de sincronía sirve, se agregó temporalmente `phone: str | None` a `User` sin generar migración. La prueba falló como se esperaba:

```text
Differences: [('add_column', None, 'users', Column('phone', AutoString(), table=<users>))]
```

---

## 6. Resultados de la ejecución

Ejecutado el 11 de noviembre de 2026.

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
$ uv run pytest -q -rx
.....................................xxxxx.............................. [ 58%]
....................................................                     [100%]
XFAIL tests/api/test_known_issues.py::test_h1_suspended_business_cannot_login - H1: login does not check the business status
XFAIL tests/api/test_known_issues.py::test_h2_token_is_invalid_after_logout - H2: logout only deletes the cookie; JWT stays valid
XFAIL tests/api/test_known_issues.py::test_h3_admin_cannot_deactivate_self - H3: an admin can deactivate their own account
XFAIL tests/api/test_known_issues.py::test_h4_repeated_failed_logins_are_throttled - H4: no rate limit on failed logins
XFAIL tests/api/test_known_issues.py::test_h5_blank_name_is_rejected - H5: names made only of spaces pass validation
119 passed, 5 xfailed in 7.73s
```

### PostgreSQL 18.6

```text
$ TEST_DATABASE_URL=postgresql+psycopg://...@localhost:5433/memberplus_test uv run pytest -q
119 passed, 5 xfailed in 22.83s
```

Se ejecutó dos veces seguidas con el mismo resultado: las pruebas no dependen del orden ni dejan datos.

### Cobertura

```text
$ uv run pytest --cov
Name                       Stmts   Miss Branch BrPart  Cover
------------------------------------------------------------
api/v1/auth_api.py            27      0      4      0   100%
api/v1/dependencies.py        43      0     10      0   100%
api/v1/user_api.py            48      0     14      0   100%
core/config.py                28      0      2      0   100%
core/cors.py                   5      0      0      0   100%
core/security.py              16      0      0      0   100%
db/database.py                13      0      0      0   100%
main.py                       22      0      2      0   100%
models/__init__.py             3      0      0      0   100%
models/business_model.py      14      0      0      0   100%
models/user_model.py          16      0      0      0   100%
schemas/token_schema.py        5      0      0      0   100%
schemas/user_schema.py        14      0      0      0   100%
------------------------------------------------------------
TOTAL                        254      0     32      0   100%
```

El MVP pide ≥ 60 % de cobertura en `services/`. Esa carpeta todavía no existe; se medirá cuando llegue la lógica de caja (hito H2).

### Pruebas más lentas

```text
1.74s  test_h4_repeated_failed_logins_are_throttled   (11 logins con Argon2id)
0.65s  TestUpdateUser::test_update_password
0.61s  test_user_created_by_a_is_invisible_to_b
0.50s  TestCreateUser::test_created_user_can_login
0.39s  TestCreateUser::test_email_is_normalized_to_lowercase
```

Lo lento es Argon2id, que está hecho para ser costoso: verificar una contraseña tarda ~66 ms en promedio (medido con 20 verificaciones). Queda muy por debajo del criterio del MVP (login → panel en ≤ 2 s).

---

## 7. Hallazgos

Problemas encontrados durante las pruebas. Ninguno rompe lo que ya está hecho, pero conviene resolverlos antes de la demo. Cada uno tiene su prueba `xfail` en `tests/api/test_known_issues.py`.

| ID | Hallazgo | Severidad | Propuesta |
|----|----------|-----------|-----------|
| H1 | Un usuario de un negocio **suspendido** puede iniciar sesión y operar | Alta | En `login` y en `get_current_active_user`, rechazar con 403 si `business.status == suspended` |
| H2 | **Logout no invalida el token**: solo borra la cookie. Una copia del JWT (Bearer) sigue sirviendo hasta que expire (8 h) | Media | Aceptable para el MVP. Si se quiere cerrar: guardar una versión de sesión en `users` y compararla en cada petición, o bajar la expiración |
| H3 | Un admin puede **desactivarse a sí mismo** y dejar al negocio sin administrador | Media | En `/user/{id}/update`, rechazar `is_active=false` si `user_id` es el del admin actual |
| H4 | **Sin límite de intentos** de login: permite fuerza bruta | Media | Limitar por IP y email (por ejemplo `slowapi`) o un bloqueo temporal tras N fallos |
| H5 | Un **nombre de solo espacios** (`"   "`) pasa la validación | Baja | `str_strip_whitespace=True` en el `model_config` de los schemas de entrada |

También se observó, sin prueba automatizada (H6 requiere concurrencia; H7 es una decisión de diseño):

| ID | Hallazgo | Severidad | Propuesta |
|----|----------|-----------|-----------|
| H6 | Si dos peticiones crean el **mismo email al mismo tiempo**, ambas pasan la verificación y la segunda falla en la base con `IntegrityError` → **500** en vez de 409 | Baja | Capturar `IntegrityError` en `create_user` y `update_user` y responder 409 |
| H7 | Los `ENUM` se guardan en la base con el **nombre** del miembro (`'ADMIN'`, `'TRIAL'`) y la API usa el **valor** (`"admin"`, `"trial"`). No es un error, pero confunde al escribir SQL a mano (el `seed.sql` del MVP) | Baja | Decidir antes de que haya datos reales: guardar los valores en minúscula (`sa_column=Column(Enum(Role, values_callable=...))` + migración) o documentar que el SQL usa mayúsculas (ya está en [MIGRATIONS.md](MIGRATIONS.md#7-migraciones-existentes)) |

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

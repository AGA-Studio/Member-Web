# Arquitectura del backend — Member+

Documentación del backend (este repositorio). Los diagramas están en [Mermaid](https://mermaid.js.org/) y se ven directamente en GitHub y en VS Code (con la extensión *Markdown Preview Mermaid Support*).

> El código está en inglés; esta documentación, en español. Cuando un nombre aparece `así`, es el nombre exacto en el código.

## 1. Vista general

Member+ es un SaaS multi-negocio: un solo despliegue atiende a varios negocios (`Business`). Cada dato de negocio lleva `business_id`, y ese valor **siempre sale del token** del usuario, nunca del cuerpo de la petición.

```mermaid
flowchart LR
    FE["Frontend<br/>Next.js<br/>(repo aparte)"]
    IOT["Lector de caja<br/>ESP32 / webcam"]
    SW["Swagger<br/>/docs"]

    subgraph API["Backend — FastAPI (este repo)"]
        direction TB
        R["api/v1/<br/>routers"]
        D["api/v1/dependencies.py<br/>auth · roles · business_id"]
        S["schemas/<br/>DTOs Pydantic"]
        M["models/<br/>tablas SQLModel"]
        DB["db/database.py<br/>engine · session"]
        C["core/<br/>config · cors · security"]
    end

    PG[("PostgreSQL 18<br/>:5433")]
    SQ[("SQLite<br/>respaldo")]

    FE -- "HTTP + cookie httpOnly" --> R
    IOT -- "HTTP + Bearer" --> R
    SW -- "HTTP + Bearer" --> R
    R --> D
    R --> S
    R --> M
    D --> DB
    M --> DB
    D --> C
    DB --> PG
    DB -. "si DATABASE_URL está vacío" .-> SQ
```

## 2. Estructura de carpetas

```mermaid
flowchart TB
    ROOT["Member-Web/"]
    ROOT --> MAIN["main.py<br/>create_app · lifespan · CORS · routers"]
    ROOT --> CORE["core/"]
    ROOT --> DBF["db/"]
    ROOT --> MOD["models/"]
    ROOT --> SCH["schemas/"]
    ROOT --> API["api/v1/"]
    ROOT --> SRV["services/"]
    ROOT --> SCR["scripts/"]
    ROOT --> MIGR["migrations/"]
    ROOT --> TST["tests/"]
    ROOT --> CFG["pyproject.toml · uv.lock · alembic.ini<br/>docker-compose.yml · .env"]

    CORE --> C1["config.py — Settings (lee .env)"]
    CORE --> C2["cors.py — setup_cors(app)"]
    CORE --> C3["security.py — Argon2id + JWT"]
    CORE --> C4["errors.py — ApiError · ErrorCode (code estable en errores)"]
    DBF --> D1["database.py — engine · check_database_connection · get_session"]
    MIGR --> MG1["env.py — conecta Alembic con settings y models"]
    MIGR --> MG2["versions/ — una migración por cambio"]
    MOD --> M1["business_model.py — Business, BusinessStatus"]
    MOD --> M2["user_model.py — User, Role"]
    MOD --> M3["enum_utils.py — enum_values (enums en minúscula)"]
    MOD --> M4["revoked_token_model.py — RevokedToken"]
    MOD --> M5["login_attempt_model.py — LoginAttempt"]
    MOD --> M6["tier_model.py — Tier, TierFinish"]
    MOD --> M7["customer_model.py — Customer (cliente y su tarjeta)"]
    MOD --> M8["purchase_model.py — Purchase (compra = movimiento = comprobante)"]
    SRV --> SV1["auth_service.py — revocación de tokens · límite de login"]
    SRV --> SV2["tier_service.py — listar y editar niveles · reglas de rango"]
    SRV --> SV3["customer_service.py — clientes · código · estado · saldos · paginación"]
    SRV --> SV4["pricing_service.py — fórmula de caja (pura)"]
    SRV --> SV5["checkout_service.py — cobrar · comprobante · Idempotency-Key"]
    SCR --> SC1["seed.py — 2 negocios demo, usuarios, niveles, clientes y compras"]
    SCH --> S1["user_schema.py — UserCreate · UserUpdate · UserResponse · MeResponse"]
    SCH --> S4["business_schema.py — BusinessSummaryResponse"]
    SCH --> S2["token_schema.py — Token · TokenData"]
    SCH --> S3["validators.py — PersonName"]
    SCH --> S5["tier_schema.py — TierUpdate · TierResponse"]
    SCH --> S6["customer_schema.py — CustomerCreate · CustomerUpdate · CustomerResponse"]
    SCH --> S7["pagination_schema.py — PageResponse"]
    SCH --> S8["checkout_schema.py — CheckoutCreate · ReceiptResponse"]
    API --> A1["dependencies.py — CurrentUser · require_roles · BusinessId<br/>ensure_user_can_access"]
    API --> A2["auth_api.py — /auth"]
    API --> A3["user_api.py — /user"]
    API --> A4["tier_api.py — /tier"]
    API --> A5["customer_api.py — /customer"]
    API --> A6["checkout_api.py — /checkout"]
```

## 3. Modelo de datos actual

Existen las tablas de autenticación, los niveles, los clientes con su tarjeta y las compras; `python -m scripts.seed` las llena con dos negocios de demo (Café Aurora y Gimnasio Titán), sus usuarios, sus niveles, sus clientes (12 y 2) y sus compras (12 y 1).

```mermaid
erDiagram
    businesses ||--o{ users : "tiene"
    businesses ||--o{ tiers : "define"
    businesses ||--o{ customers : "tiene"
    tiers ||--o{ customers : "nivel actual"
    businesses ||--o{ purchases : "registra"
    customers ||--o{ purchases : "compra"
    users ||--o{ purchases : "cobra"
    tiers ||--o{ purchases : "nivel aplicado"

    businesses {
        int id PK
        string name
        string logo_url "nullable"
        enum status "trial | active | suspended"
        datetime created_at
    }

    users {
        int id PK
        int business_id FK "null solo para role=platform"
        string name
        string email UK
        string hashed_password "Argon2id"
        enum role "platform | admin | employee"
        bool is_active
        datetime created_at
    }

    customers {
        int id PK
        int business_id FK "índice"
        int tier_id FK "índice"
        string code "MP-XXXXX; único por negocio"
        string full_name
        string email "minúscula; único por negocio"
        string phone "nullable"
        datetime issued_at
        datetime valid_until "índice"
        datetime cancelled_at "nullable; irreversible"
        datetime created_at
    }

    purchases {
        int id PK "también id del comprobante"
        int business_id FK "índice"
        int customer_id FK "índice"
        int cashier_id FK "índice; users.id, sale del token"
        int tier_id FK "nivel aplicado"
        string tier_name "copia del nombre aplicado"
        enum tier_finish "copia del acabado aplicado"
        enum card_status "active | expired | cancelled al cobrar"
        string concept "nullable, máx. 120"
        int amount_cents "> 0"
        decimal discount_percent "aplicado; 0 si no hubo beneficios"
        int discount_cents
        int cashback_used_cents "≥ 0"
        int total_cents
        int points_earned
        int cashback_earned_cents
        int points_balance_after
        int cashback_balance_after_cents
        string idempotency_key "nullable; único por negocio"
        datetime created_at "índice"
    }

    tiers {
        int id PK
        int business_id FK "índice"
        string name "texto libre, máx. 60"
        enum finish "bronze | silver | gold | onyx"
        int price_cents "≥ 0; precio por vigencia, centavos MXN"
        decimal discount_percent "0 a 100, 2 decimales"
        int points_per_ten "≥ 0; puntos por cada $10"
        decimal cashback_percent "0 a 100, 2 decimales"
        datetime created_at
    }

    revoked_tokens {
        string jti PK "id único del JWT"
        datetime expires_at "índice; se purga al pasar"
        datetime revoked_at
    }

    login_attempts {
        string email PK "también emails que no existen"
        int failed_count
        datetime last_failed_at "índice"
        datetime locked_until "nullable"
    }
```

**Niveles (`tiers`).** Cada negocio define los suyos; el seed solo carga una plantilla (Bronce, Plata, Oro y Onyx en Café Aurora; Básico y Premium en Gimnasio Titán). `finish` es el acabado visual de la tarjeta y lo elige el negocio; el nombre es libre. Un beneficio en `0` equivale a deshabilitado para ese nivel. **El cliente sube de nivel pagando** (decisión "por cobro": mejor nivel = más beneficio y más costo), así que cada nivel tiene `price_cents` y no hay umbral de puntos; los puntos solo son un saldo. Los rangos se validan en `services/tier_service.py` (422 `tier_invalid`) y la base los repite con restricciones `CHECK` como última defensa.

`revoked_tokens` (H2) y `login_attempts` (H4) son tablas de seguridad, no datos de un negocio: no llevan `business_id` ni se relacionan con `users`. Se limpian solas: un token revocado se borra cuando ya habría expirado, y un registro de intentos se borra al iniciar sesión bien o cuando pasa la ventana de bloqueo.

### Roles

```mermaid
flowchart LR
    P["platform<br/>(nosotros)"] -- "ve estado y uso,<br/>no datos de clientes" --> B["Todos los negocios"]
    A["admin"] -- "administra" --> BA["Su negocio"]
    E["employee"] -- "opera la caja de" --> BA
```

### Estados de un negocio

```mermaid
stateDiagram-v2
    [*] --> trial: alta (por seed en el MVP)
    trial --> active: aprobado
    active --> suspended: suspender
    suspended --> active: reactivar
    trial --> suspended: suspender
```

| Estado | ¿Sus usuarios pueden entrar? |
|--------|------------------------------|
| `trial` | Sí |
| `active` | Sí |
| `suspended` | **No**: 403 `Business suspended` en el login y en cualquier petición, aunque ya tengan sesión abierta |

En la base los valores de los `ENUM` se guardan en minúscula (`'admin'`, `'suspended'`), igual que en la API. Ver [MIGRATIONS.md](MIGRATIONS.md#7-migraciones-existentes).

## 4. Endpoints

Prefijo común: `/api/v1`. Documentación interactiva en `http://127.0.0.1:8000/docs`.

| Método | Ruta | Rol requerido | Qué hace |
|--------|------|---------------|----------|
| GET | `/health` | — | Estado de la API |
| POST | `/api/v1/auth/login` | — | Login con email y contraseña; deja cookie y devuelve el token. Tras 5 intentos fallidos por email responde 429 durante 15 min |
| POST | `/api/v1/auth/logout` | — | Revoca el token de esta sesión (cookie o Bearer) y borra la cookie. Las demás sesiones del usuario siguen abiertas |
| GET | `/api/v1/auth/me` | cualquier usuario activo | Usuario de la sesión y su negocio (`business`: `id`, `name`, `logo_url`, `status`; `null` para `platform`) |
| GET | `/api/v1/user/list` | admin | Usuarios de su negocio |
| POST | `/api/v1/user/create` | admin | Crea un admin o employee en su negocio |
| GET | `/api/v1/user/{user_id}` | admin | Detalle de un usuario de su negocio |
| PATCH | `/api/v1/user/{user_id}/update` | admin | Edita nombre, email, contraseña o `is_active`. Un admin no puede desactivarse a sí mismo (400) |
| GET | `/api/v1/tier/list` | admin, employee | Niveles de su negocio, sin paginar, del más barato al más caro (`price_cents`), con `customers_count` |
| PATCH | `/api/v1/tier/{tier_id}/update` | admin | Edita `name`, `finish`, `price_cents`, `discount_percent`, `points_per_ten`, `cashback_percent` (todos opcionales). Fuera de rango → 422 `tier_invalid` |
| GET | `/api/v1/customer/list` | admin | Clientes paginados por `full_name`. Filtros `q` (nombre, email o código), `level_id`, `status` (`active` \| `expiring` \| `expired` \| `cancelled`), `page`, `page_size` (8 por defecto, máx. 500). Una página que no existe devuelve la última |
| GET | `/api/v1/customer/summary` | admin | Conteos `all`, `active` (incluye las por vencer), `expiring`, `expired`, `cancelled` |
| GET | `/api/v1/customer/lookup` | admin, employee | Tarjeta por `code` (QR o tecleado; ignora espacios y mayúsculas). Responde también para vencidas y canceladas. 404 `customer_not_found` |
| POST | `/api/v1/customer/create` | admin | Alta con `full_name`, `email`, `phone` y `level_id` opcionales. Genera `code`, `issued_at` y `valid_until` (+12 meses). 409 `email_taken` |
| GET | `/api/v1/customer/{customer_id}` | admin | Ficha del cliente |
| PATCH | `/api/v1/customer/{customer_id}/update` | admin | Edita `full_name`, `email`, `phone` (`null` lo borra) o `level_id` (cambio de nivel). 409 `email_taken` |
| POST | `/api/v1/customer/{customer_id}/cancel` | admin | Cancela la tarjeta; irreversible y repetirlo no cambia nada |
| POST | `/api/v1/checkout/preview` | admin, employee | Mismo cuerpo que `create`; calcula y no guarda nada |
| POST | `/api/v1/checkout/create` | admin, employee | Registra la compra (`customer_id`, `amount_cents`, `concept` opcional, `use_cashback`) y devuelve el comprobante (201). Cabecera opcional `Idempotency-Key`. El cajero sale del token |
| GET | `/api/v1/checkout/{checkout_id}` | admin, employee | Comprobante. El cajero solo ve los suyos; el admin, todos los del negocio |

**Respuesta de `/auth/me`** (`MeResponse`): los campos de `UserResponse` más `business`, el resumen del negocio que el frontend muestra en el encabezado del panel y de la caja. No incluye datos de uso ni de clientes.

```json
{
  "id": 3,
  "business_id": 1,
  "name": "Luis Pérez",
  "email": "caja@cafe-aurora.mx",
  "role": "employee",
  "is_active": true,
  "created_at": "2026-11-12T23:28:01.536737Z",
  "business": { "id": 1, "name": "Café Aurora", "logo_url": null, "status": "active" }
}
```

**Errores con código estable** (`core/errors.py`): cada error de negocio responde `{"detail": "...", "code": "..."}`. El frontend elige el mensaje por `code`, así que `detail` se puede redactar distinto sin romperlo. Se lanza con `ApiError(status_code, detail, code)`; `setup_error_handlers(app)` en `main.py` agrega `code` a la respuesta. Los 422 de validación de campos siguen con la forma de FastAPI (`detail` en lista, sin `code`), y los errores que no están en esta tabla (por ejemplo `Permission denied`) solo llevan `detail`.

| `code` | HTTP | Dónde se lanza |
|--------|------|----------------|
| `invalid_credentials` | 401 | `POST /api/v1/auth/login`: email o contraseña incorrectos |
| `login_locked` | 429 | `POST /api/v1/auth/login`: email bloqueado por intentos (con `Retry-After`) |
| `user_inactive` | 403 | `ensure_user_can_access`: usuario desactivado (login y cada petición) |
| `business_suspended` | 403 | `ensure_user_can_access`: negocio suspendido (login y cada petición) |
| `not_authenticated` | 401 | `get_token_data` / `get_current_user`: sin sesión, token inválido, vencido o revocado |
| `email_taken` | 409 | `/user/create` y `/user/{user_id}/update`: email en uso |
| `tier_invalid` | 422 | `/tier/{tier_id}/update`: valor fuera de rango. `/customer/create` y `/customer/{customer_id}/update`: `level_id` inexistente, de otro negocio, o negocio sin niveles |
| `customer_not_found` | 404 | `/customer/lookup`, `/customer/{customer_id}` y sus acciones, `/checkout/create` y `/checkout/preview`: no existe o es de otro negocio |
| `amount_invalid` | 422 | `/checkout/create` y `/checkout/preview`: `amount_cents` fuera de 1 a 100 000 000. Un monto que no es entero es validación de campo (422 de FastAPI, sin `code`) |
| `checkout_not_found` | 404 | `/checkout/{checkout_id}`: no existe, es de otro negocio, o un cajero pide el comprobante de otro cajero |
| `idempotency_conflict` | 409 | `/checkout/create`: la `Idempotency-Key` ya se usó para otra compra (otro cliente, monto o concepto) |

Cada módulo nuevo agrega sus códigos a `ErrorCode` (`core/errors.py`).

**Respuesta de un nivel** (`TierResponse`). Los porcentajes salen como números JSON, no como texto:

```json
{
  "id": 3,
  "name": "Oro",
  "finish": "gold",
  "price_cents": 39900,
  "discount_percent": 15.0,
  "points_per_ten": 1,
  "cashback_percent": 3.0,
  "customers_count": 0
}
```

Reglas de `PATCH /tier/{tier_id}/update` (`services/tier_service.py`):

- `price_cents` de 0 a 100 000 000 ($1,000,000.00; 0 = nivel gratuito); `points_per_ten` de 0 a 1000; `discount_percent` y `cashback_percent` de 0 a 100 con máximo 2 decimales; `name` de 1 a 60 caracteres (se quitan espacios sobrantes). `finish` desconocido es validación de campo (422 de FastAPI, sin `code`).
- Dos niveles pueden costar lo mismo; el listado los desempata por `id`.
- Un campo en `null` cuenta como no enviado.
- El cambio aplica a compras nuevas; las anteriores guardan los valores que usaron.
- `customers_count` cuenta las tarjetas no canceladas de cada nivel, en una sola consulta (`GROUP BY`).
**Clientes y tarjetas (`customers`).** El cliente y su tarjeta son una sola fila: una tarjeta por cliente, con nivel, vigencia y estado. Los clientes no inician sesión.

- `code`: `MP-` más 5 caracteres al azar de un alfabeto sin `0/O` ni `1/I/L` (por ejemplo `MP-4F7K2`), único dentro del negocio. Es lo que lleva el QR y lo que se teclea en caja; la búsqueda ignora espacios y mayúsculas.
- `email`: se guarda en minúscula y es único por negocio (otro negocio puede tener el mismo).
- Vigencia: 12 meses desde `issued_at` (`VALIDITY_MONTHS`, fija mientras la DECISIÓN 9 no la vuelva configurable). El 31 pasa al último día de un mes más corto.
- `status` no se guarda: `cancelled` si `cancelled_at` tiene fecha (irreversible, gana sobre todo), `expired` si `valid_until` ya pasó, si no `active`. `expiring_soon` marca las activas que vencen en 30 días o menos.
- Cambio de nivel: el admin lo asigna con `level_id` en `PATCH /customer/{customer_id}/update` (el nivel se paga en caja). Sin `level_id` al crear, entra al nivel más barato.
- `points_balance`, `cashback_balance_cents` y `last_purchase_at` se calculan sumando las compras del cliente (`customer_service.balances`), en una sola consulta por página de la lista.

**Caja (`purchases`).** Una compra es a la vez el movimiento y el comprobante (`Receipt.id == Movement.id`). Los saldos del cliente no son columnas: son la suma de sus compras.

Fórmula (`services/pricing_service.py`, puro y sin base de datos; el frontend la repite para el resumen en vivo):

```
discount_cents      = round_half_up(amount_cents * discount_percent / 100)
base_cents          = amount_cents - discount_cents
cashback_used_cents = use_cashback ? min(cashback_balance_cents, base_cents) : 0
total_cents         = base_cents - cashback_used_cents
points_earned       = floor(base_cents / 1000) * points_per_ten
cashback_earned     = round_half_up(base_cents * cashback_percent / 100)
```

Ejemplo de la rúbrica, $1,000.00 en Oro (15 %, 1 punto por $10, 3 %): descuento 15 000, base 85 000, total 85 000, 85 puntos y 2 550 centavos de cashback. Está probado en `tests/unit/test_pricing_service.py` y en `tests/api/test_checkout.py`.

- Puntos y cashback se ganan sobre `base_cents`: ya descontado y antes de restar el cashback usado (DECISIÓN 4). Los puntos se redondean hacia abajo; descuento y cashback, al centavo con mitad hacia arriba.
- Solo una tarjeta `active` recibe beneficios. Una vencida o cancelada paga el monto completo y no gana ni usa nada; el comprobante lo indica con `card_status` (DECISIÓN 3).
- `use_cashback` gasta como máximo el saldo y nunca más que la base: el total puede quedar en 0, nunca negativo.
- La compra guarda lo que se aplicó (nombre y acabado del nivel, `discount_percent`, `card_status`), y también los saldos que quedaron después de ella. Editar el nivel después no cambia comprobantes viejos.
- Mientras se escribe la compra, la fila del cliente queda bloqueada (`SELECT … FOR UPDATE` en PostgreSQL), así dos cobros simultáneos no gastan dos veces el mismo cashback.
- `Idempotency-Key` (cabecera opcional, de 1 a 64 caracteres) es único por negocio. Repetir la misma clave devuelve la compra ya creada (201 con `Idempotent-Replayed: true`) en vez de cobrar otra vez. La misma clave con otro cliente, monto o concepto → 409 `idempotency_conflict`. Si dos reintentos llegan a la vez, el índice único detiene uno y se devuelve la compra del otro.
- No existe el concepto de "caja" o lector registrado (DECISIÓN 6): cada compra guarda el cajero que la cobró (`cashier_id`, sale del token).


**Validación de nombres** (`PersonName`, `schemas/validators.py`): se quitan los espacios sobrantes; solo letras (con acentos y ñ), espacios, guion y apóstrofo; mínimo 2 letras y máximo 120 caracteres. Si no se cumple → 422.

**Convención de rutas:** `/<recurso en singular>/<acción>` (`/user/create`, `/user/list`, `/user/{id}/update`). Los módulos nuevos siguen la misma forma, por ejemplo `/customer/create`.

```mermaid
flowchart LR
    ROOT["/api/v1"] --> AUTH["/auth"]
    ROOT --> USER["/user"]
    ROOT --> TIER["/tier"]
    ROOT --> CUST["/customer"]
    ROOT --> CHK["/checkout"]
    ROOT -.-> NEXT["Siguientes módulos:<br/>/movement · /platform"]

    AUTH --> L["POST /login"]
    AUTH --> LO["POST /logout"]
    AUTH --> ME["GET /me"]

    USER --> UL["GET /list"]
    USER --> UC["POST /create"]
    USER --> UG["GET /{user_id}"]
    USER --> UU["PATCH /{user_id}/update"]

    TIER --> TL["GET /list"]
    TIER --> TU["PATCH /{tier_id}/update"]

    CUST --> CL["GET /list"]
    CUST --> CS["GET /summary"]
    CUST --> CK["GET /lookup"]
    CUST --> CC["POST /create"]
    CUST --> CG["GET /{customer_id}"]
    CUST --> CU["PATCH /{customer_id}/update"]
    CUST --> CX["POST /{customer_id}/cancel"]

    CHK --> KP["POST /preview"]
    CHK --> KC["POST /create"]
    CHK --> KG["GET /{checkout_id}"]
```

## 5. Inicio y cierre de sesión

### Login

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant FE as Frontend
    participant API as auth_api.login
    participant SVC as services/auth_service
    participant SEC as core/security
    participant DB as PostgreSQL

    U->>FE: email + contraseña
    FE->>API: POST /api/v1/auth/login (form: username, password)
    API->>SVC: login_retry_after(email)
    SVC->>DB: SELECT login_attempts
    alt email bloqueado (5 fallos)
        API-->>FE: 429 Too many failed login attempts + Retry-After
    end
    API->>DB: SELECT user WHERE email = ?
    API->>SEC: verify_password(password, hashed_password)
    alt credenciales incorrectas
        API->>SVC: register_failed_login(email)
        SVC->>DB: failed_count + 1 (bloquea al llegar a 5)
        API-->>FE: 401 Incorrect email or password
    else contraseña correcta
        API->>SVC: clear_failed_logins(email)
        alt usuario inactivo
            API-->>FE: 403 Inactive user
        else su negocio está suspendido
            API-->>FE: 403 Business suspended
        else correcto
            API->>SEC: create_access_token(user_id, role, business_id) + jti único
            SEC-->>API: JWT (HS256, expira en 480 min)
            API-->>FE: 200 {access_token} + Set-Cookie access_token (httpOnly)
        end
    end
```

### Límite de intentos (H4)

```mermaid
stateDiagram-v2
    [*] --> Libre
    Libre --> Contando: login fallido
    Contando --> Contando: fallo 2 a 4 (401)
    Contando --> Libre: login correcto (se borra el contador)
    Contando --> Libre: pasan 15 min sin fallos
    Contando --> Bloqueado: fallo 5 (401)
    Bloqueado --> Bloqueado: cualquier intento (429)
    Bloqueado --> Libre: pasan 15 min
```

- Es por email, en minúscula, y cuenta igual para emails que no existen, así que no revela cuáles existen.
- Durante el bloqueo, ni la contraseña correcta entra; si no, el bloqueo no frenaría un ataque.
- Configurable con `LOGIN_MAX_ATTEMPTS` (5) y `LOGIN_LOCKOUT_MINUTES` (15).
- Contra: alguien que conozca un email puede bloquearlo 15 minutos a propósito. Se acepta para el MVP; la alternativa (contar por IP) no es confiable detrás del proxy de Cloudflare y Coolify.

### Logout (H2)

```mermaid
sequenceDiagram
    autonumber
    participant C as Cliente (frontend, lector o Swagger)
    participant API as auth_api.logout
    participant SVC as services/auth_service
    participant DB as PostgreSQL

    C->>API: POST /api/v1/auth/logout (cookie o Bearer)
    alt token válido
        API->>SVC: revoke_token(jti, exp)
        SVC->>DB: DELETE revoked_tokens expirados
        SVC->>DB: INSERT revoked_tokens (jti, expires_at)
    else sin token, inválido o vencido
        Note over API: nada que revocar
    end
    API-->>C: 204 + borra la cookie
    C->>API: GET /api/v1/auth/me con el mismo token
    API->>DB: ¿jti en revoked_tokens?
    API-->>C: 401
```

Un JWT no se puede "borrar": sigue siendo válido hasta su `exp`. Por eso cada token lleva un `jti` único y el logout lo guarda en `revoked_tokens`. Solo se cierra **esa** sesión; si el usuario entró desde otro equipo, esa otra sesión sigue abierta. Los tokens emitidos antes de este cambio no tienen `jti` y se rechazan: hay que volver a iniciar sesión una vez.

## 6. Petición autenticada y aislamiento entre negocios

Toda ruta protegida pasa por las dependencias de `api/v1/dependencies.py`. Si el recurso pertenece a otro negocio se responde **404**, igual que si no existiera, para no revelar que existe.

```mermaid
sequenceDiagram
    autonumber
    participant C as Cliente HTTP
    participant DEP as dependencies.py
    participant R as user_api
    participant DB as PostgreSQL

    C->>DEP: GET /api/v1/user/7 (cookie o Bearer)
    DEP->>DEP: get_token_data: decodifica el JWT
    DEP->>DB: ¿jti en revoked_tokens?
    alt sin token, token inválido o revocado
        DEP-->>C: 401
    end
    DEP->>DB: get_current_user: SELECT user por id
    DEP->>DB: get_current_active_user: is_active y estado del negocio
    alt usuario inactivo o negocio suspendido
        DEP-->>C: 403
    end
    DEP->>DEP: require_roles(admin)
    alt rol sin permiso
        DEP-->>C: 403 Permission denied
    end
    DEP->>DEP: get_business_id: business_id del usuario
    DEP->>R: get_user(user_id=7, business_id)
    R->>DB: SELECT user 7
    alt no existe o es de otro negocio
        R-->>C: 404 User not found
    else mismo negocio
        R-->>C: 200 UserResponse
    end
```

### Cadena de dependencias

```mermaid
flowchart LR
    RT["get_request_token<br/>cookie o Bearer"] --> T
    T["get_token_data<br/>JWT → TokenData<br/>401 si el jti está revocado"] --> CU["get_current_user<br/>User desde la BD"]
    CU --> CA["get_current_active_user<br/>= CurrentUser<br/>ensure_user_can_access:<br/>403 si inactivo o negocio suspendido"]
    CA --> RR["require_roles(...)<br/>403 si el rol no coincide"]
    CA --> BI["get_business_id<br/>= BusinessId"]
    SD["get_session<br/>= SessionDep"] --> CU
    SD --> CA
    SD --> T
    LOGIN["auth_api.login"] -. "misma regla" .-> CA
```

## 7. Arranque de la aplicación

```mermaid
flowchart TB
    MIG["alembic upgrade head<br/>(antes de arrancar)"] -.-> START
    START["uvicorn main:app"] --> CFG["core/config.py<br/>Settings lee .env"]
    CFG --> ENG["db/database.py<br/>crea engine (Postgres o SQLite)"]
    ENG --> APP["create_app()"]
    APP --> CORS["setup_cors(app)"]
    APP --> ROUT["include_router por cada API_V1_ROUTERS<br/>con prefijo /api/v1"]
    APP --> LS["lifespan: check_database_connection()<br/>SELECT 1"]
    LS --> READY["API lista en :8000"]
```

La app **no crea tablas**: el esquema lo maneja Alembic. Detalle en [MIGRATIONS.md](MIGRATIONS.md).

## 8. Cómo agregar un módulo nuevo

```mermaid
flowchart LR
    A["1. models/x_model.py<br/>tabla con business_id"] --> B["2. models/__init__.py<br/>importar el modelo"]
    B --> C["3. schemas/x_schema.py<br/>XCreate · XUpdate · XResponse"]
    C --> D["4. api/v1/x_api.py<br/>router /x con BusinessId"]
    D --> E["5. main.py<br/>agregar a API_V1_ROUTERS"]
    E --> MG["6. alembic revision --autogenerate<br/>y alembic upgrade head"]
    MG --> F["7. tests/<br/>incluye prueba de aislamiento"]
```

Reglas para todos los módulos:

- Toda tabla de datos de negocio lleva `business_id` y toda consulta filtra por `BusinessId`.
- `business_id` nunca aparece en un schema de entrada (`XCreate`, `XUpdate`).
- Un recurso de otro negocio responde 404.
- Los schemas de salida nunca exponen campos sensibles (`hashed_password`, tokens).
- Los nombres de personas (clientes incluidos) usan `PersonName`.
- Todo `Enum` de un modelo se declara con `sa_type=sa.Enum(X, name="x", values_callable=enum_values)` para guardarse en minúscula.

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
    DBF --> D1["database.py — engine · check_database_connection · get_session"]
    MIGR --> MG1["env.py — conecta Alembic con settings y models"]
    MIGR --> MG2["versions/ — una migración por cambio"]
    MOD --> M1["business_model.py — Business, BusinessStatus"]
    MOD --> M2["user_model.py — User, Role"]
    MOD --> M3["enum_utils.py — enum_values (enums en minúscula)"]
    MOD --> M4["revoked_token_model.py — RevokedToken"]
    MOD --> M5["login_attempt_model.py — LoginAttempt"]
    SRV --> SV1["auth_service.py — revocación de tokens · límite de login"]
    SCR --> SC1["seed.py — 2 negocios demo y sus usuarios"]
    SCH --> S1["user_schema.py — UserCreate · UserUpdate · UserResponse · MeResponse"]
    SCH --> S4["business_schema.py — BusinessSummaryResponse"]
    SCH --> S2["token_schema.py — Token · TokenData"]
    SCH --> S3["validators.py — PersonName"]
    API --> A1["dependencies.py — CurrentUser · require_roles · BusinessId<br/>ensure_user_can_access"]
    API --> A2["auth_api.py — /auth"]
    API --> A3["user_api.py — /user"]
```

## 3. Modelo de datos actual

Solo existen las tablas necesarias para autenticación; `python -m scripts.seed` las llena con dos negocios de demo (Café Aurora y Gimnasio Titán) y sus usuarios. Clientes, tarjetas, niveles, compras y movimientos se agregan en los hitos H1 y H2 del MVP.

```mermaid
erDiagram
    businesses ||--o{ users : "tiene"

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

**Validación de nombres** (`PersonName`, `schemas/validators.py`): se quitan los espacios sobrantes; solo letras (con acentos y ñ), espacios, guion y apóstrofo; mínimo 2 letras y máximo 120 caracteres. Si no se cumple → 422.

**Convención de rutas:** `/<recurso en singular>/<acción>` (`/user/create`, `/user/list`, `/user/{id}/update`). Los módulos nuevos siguen la misma forma, por ejemplo `/customer/create`.

```mermaid
flowchart LR
    ROOT["/api/v1"] --> AUTH["/auth"]
    ROOT --> USER["/user"]
    ROOT -.-> NEXT["Siguientes módulos:<br/>/customer · /membership · /tier<br/>/checkout · /movement · /platform"]

    AUTH --> L["POST /login"]
    AUTH --> LO["POST /logout"]
    AUTH --> ME["GET /me"]

    USER --> UL["GET /list"]
    USER --> UC["POST /create"]
    USER --> UG["GET /{user_id}"]
    USER --> UU["PATCH /{user_id}/update"]
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

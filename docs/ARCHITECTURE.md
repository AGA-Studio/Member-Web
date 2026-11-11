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
    ROOT --> TST["tests/"]
    ROOT --> CFG["pyproject.toml · uv.lock · requirements.txt<br/>docker-compose.yml · .env"]

    CORE --> C1["config.py — Settings (lee .env)"]
    CORE --> C2["cors.py — setup_cors(app)"]
    CORE --> C3["security.py — Argon2id + JWT"]
    DBF --> D1["database.py — engine · create_db_and_tables · get_session"]
    MOD --> M1["business_model.py — Business, BusinessStatus"]
    MOD --> M2["user_model.py — User, Role"]
    SCH --> S1["user_schema.py — UserCreate · UserUpdate · UserResponse"]
    SCH --> S2["token_schema.py — Token · TokenData"]
    API --> A1["dependencies.py — CurrentUser · require_roles · BusinessId"]
    API --> A2["auth_api.py — /auth"]
    API --> A3["user_api.py — /user"]
```

## 3. Modelo de datos actual

Solo existen las tablas necesarias para autenticación. Clientes, tarjetas, niveles, compras y movimientos se agregan en los hitos H1 y H2 del MVP.

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
```

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

## 4. Endpoints

Prefijo común: `/api/v1`. Documentación interactiva en `http://127.0.0.1:8000/docs`.

| Método | Ruta | Rol requerido | Qué hace |
|--------|------|---------------|----------|
| GET | `/health` | — | Estado de la API |
| POST | `/api/v1/auth/login` | — | Login con email y contraseña; deja cookie y devuelve el token |
| POST | `/api/v1/auth/logout` | — | Borra la cookie de sesión |
| GET | `/api/v1/auth/me` | cualquier usuario activo | Usuario de la sesión |
| GET | `/api/v1/user/list` | admin | Usuarios de su negocio |
| POST | `/api/v1/user/create` | admin | Crea un admin o employee en su negocio |
| GET | `/api/v1/user/{user_id}` | admin | Detalle de un usuario de su negocio |
| PATCH | `/api/v1/user/{user_id}/update` | admin | Edita nombre, email, contraseña o `is_active` |

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

## 5. Inicio de sesión

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant FE as Frontend
    participant API as auth_api.login
    participant SEC as core/security
    participant DB as PostgreSQL

    U->>FE: email + contraseña
    FE->>API: POST /api/v1/auth/login (form: username, password)
    API->>DB: SELECT user WHERE email = ?
    DB-->>API: User | null
    API->>SEC: verify_password(password, hashed_password)
    alt credenciales incorrectas
        API-->>FE: 401 Incorrect email or password
    else usuario inactivo
        API-->>FE: 403 Inactive user
    else correcto
        API->>SEC: create_access_token(user_id, role, business_id)
        SEC-->>API: JWT (HS256, expira en 480 min)
        API-->>FE: 200 {access_token} + Set-Cookie access_token (httpOnly)
    end
```

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
    alt sin token o token inválido
        DEP-->>C: 401
    end
    DEP->>DB: get_current_user: SELECT user por id
    DEP->>DEP: get_current_active_user: is_active
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
    T["get_token_data<br/>cookie o Bearer → TokenData"] --> CU["get_current_user<br/>User desde la BD"]
    CU --> CA["get_current_active_user<br/>= CurrentUser"]
    CA --> RR["require_roles(...)<br/>403 si el rol no coincide"]
    CA --> BI["get_business_id<br/>= BusinessId"]
    SD["get_session<br/>= SessionDep"] --> CU
```

## 7. Arranque de la aplicación

```mermaid
flowchart TB
    START["uvicorn main:app"] --> CFG["core/config.py<br/>Settings lee .env"]
    CFG --> ENG["db/database.py<br/>crea engine (Postgres o SQLite)"]
    ENG --> APP["create_app()"]
    APP --> CORS["setup_cors(app)"]
    APP --> ROUT["include_router por cada API_V1_ROUTERS<br/>con prefijo /api/v1"]
    APP --> LS["lifespan: create_db_and_tables()"]
    LS --> READY["API lista en :8000"]
```

## 8. Cómo agregar un módulo nuevo

```mermaid
flowchart LR
    A["1. models/x_model.py<br/>tabla con business_id"] --> B["2. models/__init__.py<br/>importar el modelo"]
    B --> C["3. schemas/x_schema.py<br/>XCreate · XUpdate · XResponse"]
    C --> D["4. api/v1/x_api.py<br/>router /x con BusinessId"]
    D --> E["5. main.py<br/>agregar a API_V1_ROUTERS"]
    E --> F["6. tests/<br/>incluye prueba de aislamiento"]
```

Reglas para todos los módulos:

- Toda tabla de datos de negocio lleva `business_id` y toda consulta filtra por `BusinessId`.
- `business_id` nunca aparece en un schema de entrada (`XCreate`, `XUpdate`).
- Un recurso de otro negocio responde 404.
- Los schemas de salida nunca exponen campos sensibles (`hashed_password`, tokens).

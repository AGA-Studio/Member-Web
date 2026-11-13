# Criterios de revisión — Member+

Lo que un cambio no puede romper, en una página.

Este archivo lo lee `scripts/review_pr.py`, que comenta los PRs automáticamente. **No es la fuente de verdad**: la wiki manda (`wiki.neyzt.org`, colección `9no`) y este archivo es su resumen para revisar. Si aquí dice una cosa y la wiki otra, gana la wiki y esto se corrige.

> Última sincronización con la wiki: **12 de noviembre de 2026**.
> Fuentes: *Decisiones por validar*, *MVP*, *Requisitos de referencia*, más `AGENTS.md` y `docs/ARCHITECTURE.md` de este repositorio.

## 1. Decisiones cerradas

Un PR no las contradice. Si de verdad hay que cambiarlas, se cambia primero la casilla en la wiki.

| Tema | Decisión | Cómo se ve en el código |
|------|----------|-------------------------|
| Multi-negocio | Un despliegue, muchos negocios dentro | `business_id` en cada tabla de negocio, tomado del token |
| Separación de datos | `negocio_id` desde el token, nunca del cliente | Dependencia `BusinessId`; el campo no aparece en schemas de entrada |
| Roles | `platform`, `admin`, `employee` | `Role`; el dueño de plataforma no ve datos de clientes |
| Niveles | Cada negocio define los suyos | Básico/Plata/Oro son solo plantilla inicial |
| Negocio al entrar | Por el usuario: el token lleva su negocio | Sin subdominios en el prototipo |
| Lector | Pertenece a un negocio, por código y token propio revocable | El login del empleado no sirve para el lector |
| Compra | Monto y concepto libre | Sin catálogo, sin inventario, sin artículos |
| Puntos | Historial de movimientos, no una columna del cliente | El saldo se calcula sumando movimientos (cerrada el 12 nov 2026) |
| Orden del cálculo | Descuento primero; puntos y cashback sobre lo ya descontado | Ver el ejemplo de la sección 4 |
| Beneficios simultáneos | Los tres aplican a la vez si el negocio los habilita | Descuento, puntos y cashback en la misma compra |
| Cashback | Se acumula y se aplica en la compra siguiente con aprobación del cliente | Saldo de cashback separado del de puntos |
| Subir de nivel | Por cobro | Mejor nivel = más beneficio y más costo |
| Vigencia | Precio por nivel (`price_cents`); meses configurables por negocio más adelante, renovación manual | Por ahora **12 meses fijos** (`VALIDITY_MONTHS`, corregida el 13 nov 2026); sin cobro automático |
| Pagos de membresía | Se registran en tabla simple | Monto, fecha, método y quién lo registró; sin pasarela |
| Cliente | No tiene cuenta | Solo administrador y empleado inician sesión |
| Tarjeta | Una sola entidad con nivel, estado y vigencia | Una tarjeta por cliente; sin tabla "membresía" aparte |
| Numeración | Id único global; se imprime un código corto aleatorio `MP-XXXXX`, único por negocio | 5 caracteres sin `0/O/1/I/L`; no es correlativo (corregida el 13 nov 2026) |
| Caja | QR impreso con código corto y tecleable | El QR lleva solo el código, no un UUID; si el lector falla se teclea |
| Identidad | **Sin reconocimiento facial en ningún punto** | No se guardan fotos ni datos biométricos; se retiró RF-11 |
| Auth | JWT en cookie httpOnly y Argon2id | Sin NextAuth, sin Supabase |
| Migraciones | Alembic; la app no crea tablas | Cada cambio de modelo lleva su migración en el mismo commit |
| Ramas | `main` es la única rama de integración | Sin `develop`; PR siempre contra `main` |
| Despliegue | GHCR + `docker pull` en Coolify | Migraciones en el entrypoint: si fallan, la API no arranca |
| Hostnames | App en `memberplus.neyzt.org`, API en `api-memberplus.neyzt.org` | Next reescribe `/api/*`: cookie de primera parte, sin CORS en producción. **Guion y no punto**: el SSL Universal de Cloudflare solo cubre un nivel de subdominio |
| Dueño de los datos | El negocio; Member+ solo los procesa | Dos avisos de privacidad |
| Respaldo | `pg_dump` diario + restic, restauración probada | — |

### Hallazgos ya decididos (H1–H7)

| Caso | Decisión |
|------|----------|
| Negocio suspendido (H1) | No inicia sesión: 403, y se cortan sus sesiones abiertas |
| Admin desactivándose (H3) | 400: un negocio no se queda sin administrador |
| Nombres (H5) | Mínimo 2 letras; letras con acentos y ñ, espacios, guion y apóstrofo |
| Enums (H7) | En minúscula (`admin`, `suspended`), igual que en la API |
| Logout (H2) | Revoca el token de esa sesión: cualquier copia responde 401 |
| Intentos de login (H4) | 5 fallidos por email → 429 y 15 minutos de bloqueo |
| Email duplicado concurrente (H6) | 409, sin cambios parciales |

## 2. Decisiones abiertas

**Cinco casillas sin marcar.** Un PR no las resuelve: si el cambio las toca, se pide la decisión y no se asume. Lo que sigue entre paréntesis es lo que el MVP asume hoy, para que el código no se contradiga, no una decisión tomada.

| Abierta | Lo que asume el MVP |
|---------|---------------------|
| Alta de negocio | Por script o seed; sin formulario público ni aprobación en pantalla |
| Planes y cobro | Fuera del prototipo, sin pasarela |
| Frontend Next como cliente puro | Sí: sin rutas API propias en Next |
| Placa ESP32-S3 exacta | N16R8 con cámara, por confirmar antes de comprar |
| Wi-Fi, energía y montaje | Portal cautivo, fuente de 5 V 2 A, carcasa |

## 3. Fuera del alcance de lo que se construye ahora

Pantalla de registro de negocio y su aprobación · planes y cobro (pantallas 5 y 14) · usuarios (11) y dispositivos (12) · configuración (13) y detalle del negocio (4) · reconocimiento facial · catálogo o inventario · canje de puntos · portal del cliente · sucursales · app móvil · reportes.

## 4. Reglas con número

Ejemplo que debe salir bien (compra de $1,000 en nivel Oro):

```
descuento  = 1000 * 0.15            = 150   (primero)
base       = 1000 - 150             = 850
puntos     = sobre 850
cashback   = sobre 850
```

| Regla | Número |
|-------|--------|
| Login → panel | ≤ 2 s |
| Buscar tarjeta por código | ≤ 1 s |
| Registrar compra → comprobante | ≤ 2 s |
| Filas de otro negocio visibles | **0**, comprobado por prueba automática |
| `docker compose up` desde cero | ≤ 3 min, sin internet |
| Cobertura de `services/` | ≥ 60 % |
| Intentos fallidos de login por email | 5 → 429 y 15 min |
| Nombres de persona | mínimo 2 letras |

## 5. Lo que ya vigila `tests/rules/` — no lo reportes

Estas reglas son pruebas que corren en cada PR. Si el diff las rompe, CI se pone rojo solo; repetirlas en un comentario es ruido:

- `business_id` en schemas de entrada, o credenciales en schemas de salida.
- `async def` en `api/`, `core/`, `db/`, `models/`, `schemas/`, `scripts/`, `services/`.
- Rutas fuera de `/<recurso>/<acción>`, o endpoints fuera de `/api/v1`.
- Router creado y no registrado en `API_V1_ROUTERS`.
- Módulo con `BusinessId` sin prueba de aislamiento.
- Tabla de `models/` que no está en el `erDiagram`, o ruta que no está en la tabla de endpoints de `ARCHITECTURE.md`.

Tampoco son tema de este revisor: estilo y formato (Ruff), nombres, rendimiento, cobertura de pruebas y gusto personal.

## 6. Archivos compartidos

Tocarlos exige decirlo en el cuerpo del PR, porque otra rama en vuelo puede estar en lo mismo:

`main.py` · `core/` · `pyproject.toml` · `uv.lock` · `migrations/` · `.env.example` · `.github/workflows/` · `docker-compose.yml` · `tests/conftest.py` · `AGENTS.md` · `CLAUDE.md`

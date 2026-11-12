# Despliegue — Member-Web

El API se despliega como **imagen Docker** construida en GitHub Actions y publicada en **GHCR**. Coolify no construye nada: solo hace `docker pull` y arranca el contenedor.

**Estado actual (12 nov 2026).** Sirviendo en `https://api-memberplus.neyzt.org` — proyecto **Member+** de Coolify, imagen `ghcr.io/aga-studio/member-web:0.0.1`, base `memberplus` en el PostgreSQL del mismo proyecto. **El deploy es deliberado**: un merge a `main` publica imagen pero **no** despliega; para publicar se cambia el tag de la app y se redespliega.

| Host | Qué sirve |
|---|---|
| `memberplus.neyzt.org` | **Frontend** — reservado, todavía sin desplegar |
| `api-memberplus.neyzt.org` | **API** — en producción desde el 12 nov 2026 |

> Arquitectura: [ARCHITECTURE.md](ARCHITECTURE.md) · CI: [CI.md](CI.md) · Migraciones: [MIGRATIONS.md](MIGRATIONS.md)

## Índice

1. [Por qué así](#1-por-qué-así)
2. [Piezas](#2-piezas)
3. [Qué publica cada evento](#3-qué-publica-cada-evento)
4. [Configurar Coolify (una vez)](#4-configurar-coolify-una-vez)
5. [Variables de entorno](#5-variables-de-entorno)
6. [Migraciones y datos](#6-migraciones-y-datos)
7. [Rollback](#7-rollback)
8. [Probar la imagen en local](#8-probar-la-imagen-en-local)
9. [Problemas comunes](#9-problemas-comunes)

---

## 1. Por qué así

| Construir en Coolify | Construir en GitHub (esto) |
|---|---|
| El LXC gasta CPU y RAM en cada build | El build corre en el runner de GitHub |
| Cada deploy baja dependencias nuevas | Las dependencias quedan congeladas en la imagen |
| La imagen desplegada no es la que pasó CI | Se despliega exactamente lo que validó `lint` + `test` + `test (postgres)` |
| Rollback = reconstruir | Rollback = cambiar un tag |

El repo es público, así que el registro y los minutos de Actions no cuestan nada adicional.

---

## 2. Piezas

| Archivo | Qué hace |
|---|---|
| `Dockerfile` | Dos etapas: dependencias con uv y runtime limpio, usuario sin privilegios (uid 10001), `HEALTHCHECK` contra `/health` |
| `docker/entrypoint.sh` | Aplica `alembic upgrade head` y arranca uvicorn; si la migración falla, el contenedor **no** arranca |
| `.dockerignore` | Deja fuera `tests/`, `docs/`, `.github/`, `.env`, caches y bases locales |
| `.github/workflows/image.yml` | Construye, publica en GHCR y avisa a Coolify |

La imagen final no lleva `tests/`, ni `.git`, ni `.env`, ni el CLI de uv. Todo lo que trae es lo que necesita para migrar y servir.

**Carpeta nueva de código = línea nueva en el `Dockerfile`.** El `Dockerfile` copia cada paquete por nombre (`api/`, `core/`, `db/`, `models/`, `schemas/`, `services/`…). Si se crea otra carpeta con código Python y no se agrega su `COPY`, la imagen no arranca. Para que eso falle al construir y no en Coolify, el `Dockerfile` ejecuta `python -c "import main"` al final de la etapa de dependencias: si falta un paquete, la construcción se cae con `ModuleNotFoundError` y no se publica la imagen.

---

## 3. Qué publica cada evento

| Evento | Tags en GHCR |
|---|---|
| push a `main` | `sha-<7>`, `latest` |
| release `v0.0.1` | `sha-<7>`, `0.0.1`, `0.0` |
| `workflow_dispatch` | `sha-<7>` |

**El tag de la imagen no lleva la `v`.** `docker/metadata-action` con `pattern={{version}}` quita el prefijo: un release `v0.0.1` publica `0.0.1` y `0.0`, no `v0.0.1`. Verificado en GHCR.

`sha-<7>` es el que se usa para rollback: es inmutable y apunta a un commit exacto. `latest` se mueve en cada push a `main`; **para producción se pinnea el tag de la versión (`0.0.1`), nunca `latest`**.

**Despliegue deliberado.** La app de Coolify apunta a un tag de versión fijo, así que mergear a `main` o publicar una imagen nueva **no** cambia producción. El flujo es:

```bash
gh release create v0.0.2 --target main --generate-notes   # 1. publica la imagen
# 2. en Coolify: cambiar el tag de la app a 0.0.2 y Redeploy
```

Rollback: mismo procedimiento hacia atrás con el tag anterior. Los tags `v*` de prerelease (`v0.1.0-rc.1`) generan imagen para probar, pero no se despliegan salvo que alguien mueva el tag a mano — que es justo lo que se quiere.

El webhook automático (sección 4, paso 7) es **opcional** y solo tiene sentido con un tag móvil. Mientras el modelo sea deliberado, no hace falta.

---

## 4. Configurar Coolify (una vez)

1. **Paquete público en GHCR.** El paquete nace privado aunque el repo sea público. En GitHub → *Packages* → `member-web` → *Package settings* → *Change visibility* → **Public**. Si prefieres dejarlo privado, agrega en Coolify una credencial de registro con un token de solo lectura (`read:packages`).
2. **Postgres.** Crear el servicio PostgreSQL 18 en Coolify (sin puerto público) y anotar su URL **interna**. No uses el compose de desarrollo: ese es solo para tu máquina.
   - **Crea una base propia**, en el terminal del recurso: `psql -U postgres -c "CREATE DATABASE memberplus;"`. La URL interna que entrega Coolify termina en `/postgres`; si se deja así, las tablas viven en la base por defecto y `memberplus` queda vacía (un `pg_dump` de ella saldría en blanco).
3. **Aplicación.** Nuevo recurso → *Docker Image* → `ghcr.io/aga-studio/member-web:<versión>` (p. ej. `0.0.1`). Puerto expuesto **8000**.
   - **Deja el healthcheck de Coolify apagado.** Para recursos de tipo *Docker Image*, Coolify lo implementa con `curl` o `wget` **dentro** del contenedor, y `python:3.14-slim` no trae ninguno de los dos: el contenedor quedaría `unhealthy` para siempre aunque la API responda, y el deploy se marcaría fallido. La imagen ya declara su propio `HEALTHCHECK` contra `/health` usando la stdlib, y Coolify muestra ese estado sin configurar nada. Si de todos modos quieres que Coolify lo evalúe, usa el tipo **`cmd`** con `python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)"`, nunca `http`.
4. **Variables** (ver sección 5). Como mínimo, `DATABASE_URL`, `SECRET_KEY`, `COOKIE_SECURE=true` y `CORS_ORIGINS`.
5. **Dominio.** `api-memberplus.neyzt.org` sobre el wildcard `*.neyzt.org` que ya apunta al LXC. Traefik emite el router por app; no hay que abrir puertos.
   - **El backend NO va en `memberplus.neyzt.org`**: ese nombre es del frontend. El reparto es `memberplus.neyzt.org` → frontend y `api-memberplus.neyzt.org` → API.
   - **Un solo nivel de subdominio.** `api.memberplus.neyzt.org` (dos niveles) resuelve en DNS pero **falla el handshake TLS**: el certificado Universal de Cloudflare solo cubre `neyzt.org` y `*.neyzt.org`. Para usar subdominios anidados hace falta Advanced Certificate Manager (de pago). Por eso el guion en vez del punto.
   - Coolify **genera un dominio aleatorio** `<uuid>.<ip>.sslip.io` al crear la app: bórralo. `sslip.io` resuelve a la IP que lleva embebida — tu IP de WAN, donde no hay port forwarding al LXC — y Traefik fallaría el reto ACME para un nombre inalcanzable. El campo de dominio no lleva puerto ni barra final.
6. **Datos de demo (una vez, después del primer despliegue).** En Coolify → la aplicación → *Terminal*, con `SEED_PASSWORD` definida en las variables:

   ```bash
   python -m scripts.seed
   ```

   Crea Café Aurora, Gimnasio Titán y sus usuarios (ver el README). Se puede repetir sin duplicar nada y nunca cambia la contraseña de un usuario que ya existe. Sin `SEED_PASSWORD` en producción, se niega a correr.
7. **Webhook de deploy (opcional).** Solo sirve si la app apunta a un tag **móvil**. *Application → Webhooks* → copiar la URL de deploy y el token de API, y guardarlos en el repo como secretos `COOLIFY_WEBHOOK` y `COOLIFY_TOKEN`. Con un tag de versión fijo, el webhook redespliega la misma imagen: no aporta nada al modelo deliberado.

---

## 5. Variables de entorno

| Variable | Ejemplo | Notas |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres:PASS@<host-interno>:5432/memberplus` | La interna de Coolify, no `localhost`. **Debe empezar con `postgresql+psycopg://`**: Coolify entrega la URL con `postgres://` y SQLAlchemy 2 lo rechaza. Si la contraseña trae `@`, `/`, `:` o `#`, hay que percent-codificarla |
| `SECRET_KEY` | 64 caracteres aleatorios | `python -c "import secrets; print(secrets.token_urlsafe(64))"`; si cambia, se invalidan todas las sesiones |
| `COOKIE_SECURE` | `true` | Obligatorio con HTTPS; en local va `false` |
| `CORS_ORIGINS` | `https://memberplus.neyzt.org` | El **frontend**, no la API. Lista separada por comas, sin barra final |
| `ENVIRONMENT` | `production` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Turno completo de caja |
| `LOGIN_MAX_ATTEMPTS` | `5` | Opcional. Intentos fallidos por email antes de bloquearlo (H4) |
| `LOGIN_LOCKOUT_MINUTES` | `15` | Opcional. Cuánto dura el bloqueo; responde 429 con `Retry-After` |
| `SEED_PASSWORD` | 16+ caracteres aleatorios | Solo para correr `python -m scripts.seed`; contraseña de los usuarios de demo. Obligatoria en producción |
| `PORT` | `8000` | Lo lee el entrypoint; Coolify puede inyectarlo |

Nada de esto va en el repo. `.env.example` documenta las claves con valores falsos.

---

## 6. Migraciones y datos

El entrypoint corre `alembic upgrade head` en **cada arranque**. Con el esquema al día es una operación de milisegundos que no toca datos.

- **No afecta el volumen.** El volumen es el directorio de datos de Postgres; el contenedor del API nunca escribe ahí, solo manda SQL.
- **Un fallo no deja basura.** Postgres soporta DDL transaccional y Alembic lo aprovecha: si una migración falla a medias, se revierte completa.
- **Antes de una migración destructiva** (`DROP COLUMN`, cambio de tipo), sacar respaldo:

```bash
pg_dump "$DATABASE_URL" -Fc -f respaldo-previa-$(date +%F).dump
```

- **Una sola réplica.** Dos contenedores arrancando a la vez intentarían migrar en paralelo. Si algún día hay réplicas, las migraciones se mueven a un job previo.
- Las migraciones se escriben y revisan como dice [MIGRATIONS.md](MIGRATIONS.md), y `alembic check` en CI avisa si `models/` y `migrations/` divergen.

---

## 7. Rollback

1. En Coolify, cambiar el tag de la app al `sha-<7>` anterior y redesplegar.
2. Si el esquema ya avanzó, el contenedor **se niega a arrancar** (Alembic no encuentra esa revisión en la imagen vieja). Es intencional: falla ruidoso en vez de servir con columnas que ya no existen.
3. Las dos salidas, en orden de preferencia:
   - **Volver a desplegar hacia adelante** con un tag nuevo que corrija el problema.
   - **Bajar el esquema a mano**: `alembic downgrade <revision>` desde un contenedor con la imagen nueva, y después arrancar la vieja.

Nunca se hace `downgrade` automático: una migración que borró una columna no puede devolver los datos.

---

## 8. Probar la imagen en local

```bash
docker build -t memberplus-api:local .

docker run --rm --network host \
  -e DATABASE_URL=postgresql+psycopg://memberplus:memberplus@localhost:5433/memberplus_docker \
  -e SECRET_KEY=local-secret-de-al-menos-32-caracteres \
  -p 8001:8000 memberplus-api:local
```

En los logs tiene que verse `Aplicando migraciones...` seguido de `Running upgrade`, y después `Arrancando uvicorn`. Si la base estaba vacía, la migración crea todo el esquema; el healthcheck empieza a responder en cuanto uvicorn levanta:

```bash
curl -s http://127.0.0.1:8001/health   # {"status":"ok"}
```

---

## 9. Problemas comunes

**`denied` o `unauthorized` al hacer pull en Coolify.**
El paquete de GHCR sigue privado. Ponlo público o agrega credencial de registro en Coolify.

**El contenedor arranca y muere al instante.**
Casi siempre es la migración: falta `DATABASE_URL`, la base no acepta conexiones o el esquema está adelantado. Los primeros segundos de log lo dicen con claridad (`Aplicando migraciones...` es lo último que se ve si falla ahí).

**`Can't locate revision identified by ...`**
La base está en una revisión que la imagen no conoce: se desplegó una imagen anterior sobre un esquema más nuevo. Ver [Rollback](#7-rollback).

**El healthcheck falla pero el contenedor está vivo.**
El healthcheck consulta `http://127.0.0.1:$PORT/health` dentro del contenedor. Si `PORT` no coincide con el puerto en que escucha uvicorn, nunca pasa a `healthy`. También revisa el `--start-period`: la primera comprobación no ocurre hasta pasados 20 s.

**La imagen no se actualiza en Coolify.**
Coolify no adivina que hay imagen nueva: revisa que el webhook esté configurado (`COOLIFY_WEBHOOK` + `COOLIFY_TOKEN`) o redespliega a mano. Si el tag es `sha-`, cambia el tag: ese nunca se mueve.

**`NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres`.**
La `DATABASE_URL` empieza con `postgres://`. SQLAlchemy 2 eliminó ese alias en 1.4: cámbialo a `postgresql+psycopg://`. Es el error más común de la primera puesta en marcha, y el contenedor queda en `Restarting (1)`.

**El contenedor se reinicia en bucle y el log se corta en `Aplicando migraciones...`.**
Muere en Alembic, no en uvicorn. En orden: `DATABASE_URL` con esquema malo, host inalcanzable (usaste `localhost` en vez del host interno), contraseña con caracteres sin codificar, o esquema adelantado respecto a la imagen.

**Coolify marca `unhealthy` pero `curl` al dominio responde 200.**
Tienes el healthcheck de Coolify en tipo `http` y la imagen no trae `curl` ni `wget`. Apágalo (la imagen ya chequea sola) o cámbialo a tipo `cmd`.

**El dominio `*.sslip.io` de Coolify no abre.**
Es el default generado al crear la app y apunta a la IP pública del servidor, que aquí no tiene port forwarding. Reemplázalo por el dominio real sobre `*.neyzt.org`.

**`sslv3 alert handshake failure` en un subdominio recién puesto.**
Tiene dos niveles (`api.algo.neyzt.org`). El certificado Universal de Cloudflare solo cubre `neyzt.org` y `*.neyzt.org`, un nivel; el DNS resuelve igual (la zona tiene catch-all), así que el síntoma parece un problema de Traefik y no lo es. Solución: un solo nivel con guion (`api-algo.neyzt.org`) o Advanced Certificate Manager.

**`/docs` y `/openapi.json` son públicos.**
FastAPI los expone salvo que se desactiven. Decisión pendiente: cerrarlos cuando `ENVIRONMENT=production` o dejarlos abiertos a propósito. Hoy están abiertos, y así se documentó.

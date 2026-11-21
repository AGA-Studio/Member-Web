# Despliegue — Member-Web

El API se despliega como **imagen Docker** construida en GitHub Actions y publicada en **GHCR**. Coolify no construye nada: solo hace `docker pull` y arranca el contenedor.

**Estado actual (21 nov 2026).** Sirviendo en `https://api-memberplus.neyzt.org` (API) y `https://memberplus.neyzt.org` — **host compartido entre la landing y el frontend** — proyecto **Member+** de Coolify, imágenes `ghcr.io/aga-studio/member-web:latest`, `ghcr.io/aga-studio/member-plus-frontend:latest` y `ghcr.io/aga-studio/member-plus-landing:latest`, base `memberplus` en el PostgreSQL del mismo proyecto. **Mergear a `main` despliega**: el workflow *Image* publica la imagen y llama al deploy webhook de Coolify. No hay releases obligatorios y la demo **es** producción: un solo entorno.

| Host | Qué sirve |
|---|---|
| `memberplus.neyzt.org` — `/`, `/privacidad`, `/terminos`, `/en*` y sus assets | **Landing** — desplegada el 21 nov 2026 (imagen `member-plus-landing:latest`); se indexa |
| `memberplus.neyzt.org` — rutas de la app | **Frontend** — desplegado (imagen `member-plus-frontend:latest`); noindex |
| `api-memberplus.neyzt.org` | **API** — en producción desde el 12 nov 2026 |

El host del producto lo comparten **dos contenedores** y el reparto lo hace Traefik por prioridad de regla: la landing declara su propio router (`priority=100`) con la lista exacta de sus rutas y el frontend conserva `PathPrefix(/)`. Labels exactas, verificación y rollback: `docs/DEPLOY.md` del repo [Member-Plus-Landing](https://github.com/AGA-Studio/Member-Plus-Landing).

**El navegador no llama al API directo.** Pide `/api/*` en el host del frontend y Next lo reescribe hacia el API: así la cookie httpOnly es de primera parte (sin CORS en producción y sin `SameSite=None`). El único cliente que pega al API de frente es el lector ESP32, con su token de dispositivo.

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
9. [Respaldo local de la demo (perfil stack)](#9-respaldo-local-de-la-demo-perfil-stack)
10. [Problemas comunes](#10-problemas-comunes)
11. [Respaldos de producción: base en Coolify y objetos en B2](#11-respaldos-de-producción-base-en-coolify-y-objetos-en-b2)

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

| Evento | Tags en GHCR | ¿Despliega? |
|---|---|---|
| push a `main` | `sha-<7>`, `main`, `latest` | **Sí**: el paso *Pedir deploy a Coolify* llama al webhook |
| release `v0.0.1` | `sha-<7>`, `0.0.1`, `0.0` | No: marca el hito, no toca producción |
| `workflow_dispatch` | `sha-<7>` (de la rama elegida) | Solo si se lanzó desde `main` |

**El tag de la imagen no lleva la `v`.** `docker/metadata-action` con `pattern={{version}}` quita el prefijo: un release `v0.0.1` publica `0.0.1` y `0.0`, no `v0.0.1`. Verificado en GHCR.

`sha-<7>` es el que se usa para rollback: es inmutable y apunta a un commit exacto. `latest` (y su gemelo `main`) se mueven en cada push a la rama por defecto — **nunca** con un tag `v*` — y es el que sirve Coolify: es un tag móvil a propósito, ese es el mecanismo del despliegue automático.

**Mergear a `main` despliega.** El equipo trabajaba en cambios chicos y constantes, y cortar un release por cada uno era trabajo de más; desde el 13 nov 2026 el merge es el botón de publicar:

```bash
git push origin main    # 1. el workflow Image construye y publica
# 2. el mismo run llama al webhook de Coolify (paso "Pedir deploy a Coolify")
# 3. Coolify hace pull del tag `latest` y reemplaza el contenedor
```

Cómo se comporta:

- **Si el paso del webhook falla**, la imagen queda publicada y el sitio con la versión anterior: relanzar el workflow a mano (`gh workflow run image.yml`) lo resuelve.
- **Si el secreto no existe**, el paso imprime un aviso y el deploy queda manual. Es lo que pasa en un fork o en un repo recién clonado.
- **Dos merges seguidos**: `concurrency` cancela el run anterior, así que solo el último publica y despliega. Es lo que se quiere: gana el estado final de `main`.
- **Los releases `vX.Y.Z` siguen existiendo** para marcar el hito que se presenta en la entrega (producen `0.1.0` y `0.1`), pero ya no son la vía de despliegue: un tag no dispara el webhook.
- **Cada merge aplica las migraciones** en la base de la demo (el entrypoint corre `alembic upgrade head`). Una migración rota tumba el sitio hasta redesplegar el `sha-<7>` anterior: ver la sección 7.
- **No hay entorno de demo separado.** Se evaluó una segunda app en Coolify y se descartó: duplicaría base, seed y migraciones para probar lo mismo que ya se prueba en `main`.

---

## 4. Configurar Coolify (una vez)

1. **Paquete público en GHCR.** El paquete nace privado aunque el repo sea público. En GitHub → *Packages* → `member-web` → *Package settings* → *Change visibility* → **Public**. Si prefieres dejarlo privado, agrega en Coolify una credencial de registro con un token de solo lectura (`read:packages`).
2. **Postgres.** Crear el servicio PostgreSQL 18 en Coolify (sin puerto público) y anotar su URL **interna**. No uses el compose de desarrollo como base de Coolify: ese es solo para tu máquina (sección 9).
   - **Crea una base propia**, en el terminal del recurso: `psql -U postgres -c "CREATE DATABASE memberplus;"`. La URL interna que entrega Coolify termina en `/postgres`; si se deja así, las tablas viven en la base por defecto y `memberplus` queda vacía (un `pg_dump` de ella saldría en blanco).
3. **Aplicación.** Nuevo recurso → *Docker Image* → `ghcr.io/aga-studio/member-web:latest`. Puerto expuesto **8000**. El tag es `latest` a propósito: es el que mueve cada push a `main` y el que hace funcionar el despliegue automático.
   - **Deja el healthcheck de Coolify apagado.** Para recursos de tipo *Docker Image*, Coolify lo implementa con `curl` o `wget` **dentro** del contenedor, y `python:3.14-slim` no trae ninguno de los dos: el contenedor quedaría `unhealthy` para siempre aunque la API responda, y el deploy se marcaría fallido. La imagen ya declara su propio `HEALTHCHECK` contra `/health` usando la stdlib, y Coolify muestra ese estado sin configurar nada. Si de todos modos quieres que Coolify lo evalúe, usa el tipo **`cmd`** con `python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)"`, nunca `http`.
4. **Variables** (ver sección 5). Como mínimo, `DATABASE_URL`, `SECRET_KEY`, `COOKIE_SECURE=true` y `CORS_ORIGINS`.
5. **Dominio.** `api-memberplus.neyzt.org` sobre el wildcard `*.neyzt.org` que ya apunta al LXC. Traefik emite el router por app; no hay que abrir puertos.
   - **El backend NO va en `memberplus.neyzt.org`**: ese nombre es de la landing y del frontend. El reparto es `memberplus.neyzt.org` → landing + frontend y `api-memberplus.neyzt.org` → API.
   - **Un solo nivel de subdominio.** `api.memberplus.neyzt.org` (dos niveles) resuelve en DNS pero **falla el handshake TLS**: el certificado Universal de Cloudflare solo cubre `neyzt.org` y `*.neyzt.org`. Para usar subdominios anidados hace falta Advanced Certificate Manager (de pago). Por eso el guion en vez del punto.
   - Coolify **genera un dominio aleatorio** `<uuid>.<ip>.sslip.io` al crear la app: bórralo. `sslip.io` resuelve a la IP que lleva embebida — tu IP de WAN, donde no hay port forwarding al LXC — y Traefik fallaría el reto ACME para un nombre inalcanzable. El campo de dominio no lleva puerto ni barra final.
6. **Datos de demo (una vez, después del primer despliegue).** En Coolify → la aplicación → *Terminal*, con `SEED_PASSWORD` definida en las variables:

   ```bash
   python -m scripts.seed
   ```

   Crea Café Aurora, Gimnasio Titán y sus usuarios (ver el README). Se puede repetir sin duplicar nada y nunca cambia la contraseña de un usuario que ya existe. Sin `SEED_PASSWORD` en producción, se niega a correr.
7. **Webhook de deploy (obligatorio: es el despliegue automático).** Dos piezas, una vez:
   - En Coolify → *Keys & Tokens* → *API Tokens* → crear un token con permiso **`deploy`** (solo ese). El valor se muestra una sola vez.
   - En la app → *Webhooks* → copiar **Deploy Webhook (auth required)**: `https://coolify.neyzt.org/api/v1/deploy?uuid=<uuid-de-la-app>&force=false`.

   Después, en **cada repo** (el webhook es por app; el token es el mismo):

   ```bash
   gh secret set COOLIFY_WEBHOOK --body '<url-del-deploy-webhook>'
   gh secret set COOLIFY_TOKEN --body '<token-con-permiso-deploy>'
   ```

   Con eso, el paso *Pedir deploy a Coolify* de `image.yml` hace `POST` al webhook (con `GET`, Coolify responde `405 This endpoint has changed to a POST request.`) y contesta `200` con `{"deployments":[{"resource_uuid":"…","deployment_uuid":"…"}]}`.

   **El `resource_uuid` de la respuesta es la app que se desplegó**: si no es la de este repo, el secreto `COOLIFY_WEBHOOK` está apuntando a la otra app (pasó el 13 nov: el backend desplegaba el frontend y el suyo no). El webhook es **por app**; el token es el mismo para las tres. Sin `COOLIFY_WEBHOOK` el paso solo avisa y el deploy sigue siendo manual.

   **`COOLIFY_TOKEN` es opcional** y solo se necesita si copiaste la URL de *auth required*: si la URL ya trae `?api_token=...` (el formato viejo), el paso detecta el token vacío y no manda cabecera. Mandar un `Bearer` vacío provoca 401 y tumba el run **después** de publicar la imagen.

---

## 5. Variables de entorno

| Variable | Ejemplo | Notas |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres:PASS@<host-interno>:5432/memberplus` | La interna de Coolify, no `localhost`. **Debe empezar con `postgresql+psycopg://`**: Coolify entrega la URL con `postgres://` y SQLAlchemy 2 lo rechaza. Si la contraseña trae `@`, `/`, `:` o `#`, hay que percent-codificarla |
| `SECRET_KEY` | 64 caracteres aleatorios | `python -c "import secrets; print(secrets.token_urlsafe(64))"`; si cambia, se invalidan todas las sesiones |
| `COOKIE_SECURE` | `true` | Obligatorio con HTTPS; en local va `false` |
| `CORS_ORIGINS` | `https://memberplus.neyzt.org` | Solo para **desarrollo local**. En producción el navegador llama `/api/*` en el host del frontend y Next lo reescribe hacia el API, así que no hay CORS ni `SameSite=None`. Lista separada por comas, sin barra final |
| `ENVIRONMENT` | `production` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Turno completo de caja |
| `LOGIN_MAX_ATTEMPTS` | `5` | Opcional. Intentos fallidos por email antes de bloquearlo (H4) |
| `LOGIN_LOCKOUT_MINUTES` | `15` | Opcional. Cuánto dura el bloqueo; responde 429 con `Retry-After` |
| `SEED_PASSWORD` | 16+ caracteres aleatorios | Solo para correr `python -m scripts.seed`; contraseña de los usuarios de demo. Obligatoria en producción |
| `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION` | — | Almacenamiento de imágenes. Sin `S3_ENDPOINT_URL` la API funciona igual y `/logo/update` responde 503. **En producción están puestas** desde el 14 nov 2026 con Cloudflare R2 (`S3_REGION=auto` y `S3_PUBLIC_ENDPOINT_URL` vacía); qué son exactamente y cómo se probaron, en [STORAGE.md, sección 8](STORAGE.md#8-producción) |
| `TURNSTILE_ENABLED` | `true` | Opcional, `false` por defecto. Exige Cloudflare Turnstile en el login. **Se crea al final**, después de desplegar el backend y el frontend con el widget (ver abajo) |
| `TURNSTILE_SECRET` | — | Secreto del widget «Member+ Login» de Cloudflare. Solo en las variables de Coolify, nunca en el repo ni en la wiki |
| `FRONTEND_PUBLIC_URL` | `https://memberplus.neyzt.org` | Base de los enlaces que se envían (tarjeta digital) y hostname que valida Turnstile. Vacía en local: `http://localhost:3000` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | relay de Brevo: `smtp-relay.brevo.com`, `587` | Envío de la tarjeta por correo. Sin `SMTP_HOST` la API arranca igual, pero en producción todo envío responde `email_failed`. `SMTP_TLS` acepta `starttls`, `ssl` o `none`; `SMTP_TIMEOUT_SECONDS` (10) es opcional. En producción ya están configuradas |
| `GOOGLE_WALLET_ISSUER_ID`, `GOOGLE_WALLET_SERVICE_ACCOUNT_JSON`, `GOOGLE_WALLET_ORIGINS`, `GOOGLE_WALLET_LOGO_URL` | — | Botón «Agregar a Google Wallet». Si falta cualquiera de las cuatro, la tarjeta oculta el botón y `GET /card/{token}/google-wallet` responde 503. El issuer y la cuenta de servicio salen de Google Wallet Console; el logo debe ser una URL `https` pública |
| `CARD_RATE_LIMIT_PER_MINUTE` | `30` | Opcional. Peticiones por minuto y por IP a los endpoints públicos de la tarjeta |
| `PORT` | `8000` | Lo lee el entrypoint; Coolify puede inyectarlo |

Nada de esto va en el repo. `.env.example` documenta las claves con valores falsos.

### Activar Turnstile sin romper el login

El hostname que se valida sale de `FRONTEND_PUBLIC_URL` (`memberplus.neyzt.org`), el único hostname del widget. Como mergear a `main` despliega, el orden de los PR importa:

1. Backend con la bandera **apagada** (sin `TURNSTILE_ENABLED`) y la cabecera ya soportada.
2. Frontend con el widget: manda `X-Turnstile-Token` y nadie lo exige todavía. Necesita `TURNSTILE_SITEKEY` en su app de Coolify.
3. `TURNSTILE_ENABLED=true` en la app del API (con `TURNSTILE_SECRET` ya cargado) y redesplegar.

Comprobación: un `curl -X POST https://api-memberplus.neyzt.org/api/v1/auth/login -d 'username=x@x.mx&password=x'` sin cabecera debe responder `400 {"detail": "turnstile_failed", "code": "turnstile_failed"}`. Para apagarlo de urgencia, borrar la variable (o ponerla en `false`) y redesplegar.

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

1. En Coolify → *Deployments*, o fijando el tag: poner el `sha-<7>` anterior y redesplegar. Esa imagen sigue en GHCR y es el commit exacto que funcionaba.
2. Cuando el fix esté en `main`, volver el tag a `latest` y redesplegar; los pushes a `main` lo siguen moviendo solos. Dejarlo pinneado en el `sha-<7>` congela la app sin frenar a nadie: el webhook redespliega la misma imagen que ya tiene.
3. Si el esquema ya avanzó, el contenedor **se niega a arrancar** (Alembic no encuentra esa revisión en la imagen vieja). Es intencional: falla ruidoso en vez de servir con columnas que ya no existen.
4. Las dos salidas, en orden de preferencia:
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

## 9. Respaldo local de la demo (perfil `stack`)

El compose de desarrollo levanta Postgres, Mailpit (correo) y RustFS (almacenamiento de imágenes, ver [STORAGE.md](STORAGE.md)). Para el ensayo sin internet, el mismo `docker-compose.yml` trae un perfil `stack` que suma `api` y `web` **sin construir nada**: las dos imágenes se publican en GHCR y en local solo se hace `pull`.

El perfil tiene dos usos: correr la app completa —el ensayo del respaldo y la demo— y el desarrollo del frontend por quien no toca el API ([Para quien solo toca el frontend](#para-quien-solo-toca-el-frontend)).

| Servicio | Imagen | Qué es |
|---|---|---|
| `db` | `postgres:18` | Base del stack (volumen `pgdata`) |
| `api` | `ghcr.io/aga-studio/member-web:${API_IMAGE_TAG:-latest}` | API, la misma imagen que producción. Sin variable = `latest` |
| `web` | `ghcr.io/aga-studio/member-plus-frontend:${WEB_IMAGE_TAG:-latest}` | El mismo frontend de producción. Sin variable = `latest` |

**El frontend es la misma imagen de producción.** El navegador pide `/api/*` al frontend y su proxy (`src/proxy.ts`) lo reenvía a `API_INTERNAL_URL`, que se resuelve **en runtime**: este compose la fija a `http://api:8000`, el nombre del servicio en la red de Compose. Por eso no hay un build aparte ni un tag especial, y por eso el stack funciona sin internet.

Con `pull_policy: missing` un `up` normal no refresca una imagen que ya está local: cuando el API o el frontend avancen, correr `docker compose --profile stack pull`.

### Para quien solo toca el frontend

El mismo perfil sirve para trabajar el frontend de [Member-Plus-Frontend](https://github.com/AGA-Studio/Member-Plus-Frontend) sin clonar el API de fuentes ni correr `uvicorn`: se levanta la imagen publicada y `next dev` corre en el host hablando con `127.0.0.1:8000`. No hace falta Python, `uv` ni `.venv`, y las dos imágenes son públicas en GHCR, así que tampoco `docker login`.

```bash
git clone https://github.com/AGA-Studio/Member-Web ../Member-Web
cd ../Member-Web
cp .env.example .env                          # Windows cmd: copy .env.example .env
docker compose --profile stack up -d db storage mail api
docker compose --profile stack exec api python -m scripts.seed
```

Vuelve a la carpeta del frontend y corre `npm run dev` (Next en `:3000`). Credenciales del seed: `admin@cafe-aurora.mx` / `demo12345`, y `owner@memberplus.mx` para la vista de plataforma.

Cuatro cosas que no son obvias:

- **No levantar el servicio `web`** en este caso: publica el `:3000` y pelea con `next dev`. Por eso se nombran los servicios uno por uno en vez de usar `--profile stack up` a secas.
- **`API_IMAGE_TAG` vacío vale `latest`**, el tag que mueve cada push a `main`: siempre el API de la rama principal. Pero `pull_policy: missing` **no** refresca una imagen que ya está local, así que cuando el API avance hay que correr `docker compose --profile stack pull api`.
- **En Mac con Apple Silicon las imágenes son `linux/amd64`**: Docker Desktop las emula con Rosetta. Funcionan, pero el `seed` (Argon2id) tarda decenas de segundos y parece colgado sin estarlo.
- **No dupliques este compose en el repo del frontend.** Sería una segunda fuente de verdad de `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`, `SMTP_*` y `S3_*`: cuando el API pida una variable nueva, la copia envejece en silencio y el síntoma aparece como una pantalla rota, no como "falta una variable".

### Antes del ensayo (con internet)

Sin variables el perfil ya arranca la app completa, pero el ensayo se hace **fijando los dos tags**: `latest` se mueve con cada push a `main`, así que sin fijarlos el ensayo apuntaría a lo último en vez de a lo que se ensayó.

```bash
export API_IMAGE_TAG=sha-abc1234    # sha del API que se quiere ensayar
export WEB_IMAGE_TAG=sha-abc1234    # el del frontend; mismo commit si se puede
docker compose --profile stack pull
docker compose --profile stack up -d --wait
docker compose --profile stack exec api python -m scripts.seed
```

`--wait` espera a que `db`, `api` y `web` estén `healthy`; los tres tienen healthcheck. El seed es idempotente: en `development` usa la contraseña demo conocida, en `production` exige `SEED_PASSWORD`.

### Cronometraje del criterio de H0

Con las imágenes ya descargadas, desde cero:

```bash
docker compose --profile stack down -v
time docker compose --profile stack up -d --wait
docker compose --profile stack ps        # todo healthy
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/
```

Anotar el resultado (meta: 3 minutos o menos). El seed no entra en el tiempo del `up`:

| Fecha | Con internet | Sin internet | Notas |
|---|---|---|---|
| | | | |

### Prueba sin internet

Desconectar la red y repetir `down -v` + `up -d --wait`. Si el arranque intenta descargar algo, falta el `pull` previo o el tag no está local: `docker images | grep -E "member-web|member-plus-frontend"`.

---

## 10. Problemas comunes

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

---

## 11. Respaldos de producción: base en Coolify y objetos en B2

Plan de recuperación (DRP). La decisión está cerrada en la wiki (*Decisiones por validar*: «¿Cómo se respalda?») y el diseño completo en *Servicios de terceros: Turnstile en el login y respaldos en B2*.

**Estado (17 nov 2026):** ✅ los dos respaldos corren, la copia de objetos está verificada byte a byte y la restauración **de la base** quedó probada sobre `memberplus` con el *Import backup* del panel. Detalle y costo de la prueba en [cómo se probó la restauración](#cómo-se-probó-la-restauración-17-nov-2026).

Son dos capas porque son dos cosas distintas: la **base** y los **objetos del bucket de imágenes**. El respaldo de la base no incluye los objetos, y un borrado accidental de un logo deja la fila apuntando a un archivo que ya no existe.

```mermaid
flowchart LR
    PG[("Postgres memberplus<br/>en coolify-vm")] -->|"backup nativo de Coolify<br/>10 3 * * *"| B2[("Backblaze B2<br/>bucket memberplus-restic")]
    R2[("Cloudflare R2<br/>bucket memberplus")] -->|"rclone copy (host)<br/>40 3 * * *"| B2
    B2 -->|"Restore / pg_restore"| DRILL["Base desechable<br/>memberplus_drill"]
```

### Capa 1 — la base, con el backup nativo de Coolify

| Pieza | Valor |
|-------|-------|
| Recurso | PostgreSQL del proyecto **Member+** (`bms3axi9fxhwfeoeagvrdjzc`) |
| Base respaldada | `memberplus` — se configura con **Specific databases**; ver la advertencia de abajo |
| Programación | `10 3 * * *`, en la zona horaria del servidor (campo de solo lectura) |
| Destino | backup storage `Blackblaze MemberPlus` → bucket `memberplus-restic`, región `us-west-004`, path style activo |
| Retención | 1 copia en local, que se conserva 3 días; 8 copias en B2, sin caducidad por días (`dump_all=false`) |
| Avisos | Coolify notifica el primer fallo, como máximo una vez al día, y avisa cuando vuelve a funcionar |

Los dumps locales quedan en `/data/coolify/backups/databases/<proyecto>/<recurso>/pg-dump-memberplus-*.dmp`, dentro de `coolify-vm`, y se descargan desde la misma pantalla del panel.

> **La advertencia que cuesta el respaldo entero:** el schedule se deja en *Specific databases* → `memberplus`. Con *All databases*, Coolify corre `pg_dumpall` sobre lo que el contenedor considera su base: hasta el 17 nov 2026 `POSTGRES_DB` valía `postgres` y el archivo salía con el catálogo y la base real vacía. Desde esa fecha la variable vale `memberplus`, pero el dump sigue sin ser el que se quiere: arrastra las bases del catálogo y crece con lo que no se respalda aquí. El nombre del archivo lo confirma: `pg-dump-memberplus-*.dmp`.

### Capa 2 — los objetos de imágenes, con rclone en el host

| Pieza | Valor |
|-------|-------|
| Origen | `r2:memberplus` (bucket privado; el navegador abre cada logo con una URL firmada de 1 h) |
| Script | `~/backups/scripts/backup-memberplus-images.sh` en el host, fuera de este repo |
| Destino | `b2mp:memberplus-restic/images/` — mismo bucket de B2, prefijo propio |
| Cuándo | cron `40 3 * * *`, después del respaldo de la base |
| Credenciales | token de R2 **solo lectura** y clave de B2 en `~/.config/restic/*.env` con `chmod 600` |

**`copy` y no `sync`.** `sync` espeja: lo que se borra en R2 desaparecería también de B2, que es justo lo que hay que evitar. `copy` es append-only. Y en este proyecto basta, porque cada subida estrena clave (`businesses/<id>/logo/<uuid>.webp`): nunca se sobrescribe un objeto, así que el único evento destructivo es un borrado explícito — y queda conservado en B2.

**Por qué los objetos van fuera de Coolify.** Coolify no tiene sincronizado de buckets; solo *scheduled tasks*, que corren dentro del contenedor de una app. Poner ahí el script obligaría a darle al contenedor del API una llave del bucket de respaldos —el mismo donde están los dumps de la base— y un fallo en la aplicación pasaría a ser acceso a los respaldos. En el host la llave no toca la aplicación.

### Por qué la base sí va en Coolify

Con 8.5 MB de base y un dump de ~41 KB, lo que decide no es la deduplicación ni el cifrado en cliente de restic: es que el respaldo se vea y se administre donde el equipo ya trabaja, con historial de ejecuciones y avisos incluidos. Lo que se pierde, dicho claro: el dump va **sin cifrar** al bucket. Lo compensan el bucket privado, la clave limitada a ese bucket y el cifrado en reposo de Backblaze.

Antes del 15 nov 2026 esto era un script con `restic` en el host (`backup-memberplus.sh`, repo `b2:memberplus-restic:pg`). Se retiró al pasar al respaldo nativo: su cron ya no existe y el repositorio viejo sigue en el bucket bajo el prefijo `pg/`, sin uso. Se conservó el script solo por si algún día hay que respaldar el volumen de RustFS en local.

Se usa **cron y no un timer de systemd** porque es lo que se vio en clase y basta para el prototipo.

### Cómo se restaura

**Base, desde el panel.** El *Import backup* ejecuta su script dentro del contenedor y restaura sobre `$POSTGRES_DB`; en PostgreSQL no hay selector de destino (solo en SQLite). El destino efectivo es la variable del contenedor:

```bash
lxc exec coolify-vm -- docker exec bms3axi9fxhwfeoeagvrdjzc printenv | grep ^POSTGRES_DB=
# POSTGRES_DB=memberplus
```

Ese valor es `memberplus` desde el 17 nov 2026, así que el Import escribe en la base de la app. Tres cosas que el panel no dice:

- **La ficha del recurso está desalineada.** La API del panel devuelve `postgres_db: "postgres"` mientras el contenedor tiene `memberplus`. Manda el contenedor; la ficha solo describe con qué nació. Si la base se recrea desde el panel, el contenedor nuevo nacería con `postgres` y tanto la app como el Import apuntarían al lugar equivocado.
- **La vista previa del comando no resuelve la variable:** muestra `-d "$db"`. No sirve para saber dónde va a escribir.
- **Guardar la variable no la aplica.** Hay que recrear el contenedor y volver a comprobar con el `printenv` de arriba.

Antes de importar, **Backup now**: el dump del schedule puede tener 24 h y el import corre con *Replace objects that already exist* (`--clean --if-exists`), que borra todo lo posterior. La app del API debe estar parada, porque `--clean` toma locks sobre todas las tablas.

**Base, a una base desechable (el ensayo que no toca producción).** El panel no puede elegir destino, así que el drill sigue siendo a mano:

```bash
PG=bms3axi9fxhwfeoeagvrdjzc
DUMP=/data/coolify/backups/databases/member-0/memberplus-db-bms3axi9fxhwfeoeagvrdjzc/pg-dump-memberplus-<id>.dmp

# base desechable para probar
lxc exec coolify-vm -- docker exec $PG psql -U postgres -c "CREATE DATABASE memberplus_drill;"
lxc exec coolify-vm -- bash -lc "cat '$DUMP'" | lxc exec coolify-vm -- docker exec -i $PG pg_restore -U postgres -d memberplus_drill --no-owner
lxc exec coolify-vm -- docker exec $PG psql -U postgres -c "DROP DATABASE memberplus_drill;"
```

Si el panel cambiara de destino y hay que restaurar sobre `memberplus` a mano: detener la app `MemberPlus backend` en Coolify, el mismo `pg_restore` con `--clean --if-exists`, y volver a arrancarla.

**Objetos.** Traer el objeto desde B2, a R2 o a disco:

```bash
rclone copy b2mp:memberplus-restic/images/businesses/1/logo/<uuid>.webp /tmp/
```

### Cómo se verifica

| Qué | Cómo | Estado |
|-----|------|--------|
| El respaldo de la base corre | Una ejecución por día en la pestaña *Backups*, con estado correcto y su tamaño | ✅ 15 nov 2026: `success`, 41 703 B |
| El archivo llega a B2 | El objeto aparece en el bucket `memberplus-restic` | ✅ |
| La base se puede recuperar | *Import backup* del panel sobre `memberplus` (o `pg_restore` a `memberplus_drill`) y los conteos de `businesses`, `users`, `tiers` y `customers` iguales al dump | ✅ 17 nov 2026: `exitCode: 0` y conteos idénticos |
| Los objetos se copian | `rclone size` en R2 y en B2 coincide en objetos y bytes; MD5 igual por objeto | ✅ 15 nov 2026: 2 objetos, 44 216 B, MD5 idénticos |
| Los objetos se pueden recuperar | `rclone copy` desde B2 y el archivo abre como `image/webp` | ✅ 15 nov 2026 |

### Cómo se probó la restauración (17 nov 2026)

| Qué | Resultado |
|-----|-----------|
| Vía | *Import backup* del panel sobre `memberplus-db` (`bms3axi9fxhwfeoeagvrdjzc`), archivo bajado del bucket, *Replace objects that already exist* |
| Evidencia en el panel | `activity_log` de Coolify: `operation: database_import`, `status: finished`, `exitCode: 0`, `replace_existing: true` |
| Destino real | `POSTGRES_DB=memberplus` en el contenedor, y la app tiene ahí sus conexiones |
| Resultado | Los conteos de `businesses`, `users`, `tiers` y `customers` quedaron iguales a los del dump |

**Lo que costó.** El import restauró el dump de ~24 h antes, así que las filas creadas entre el respaldo y el import se perdieron. La prueba se hizo **sobre la base viva**, no sobre una copia: para el día a día está bien porque es la única vía que ofrece el panel, pero un ensayo periódico del DRP debería ir a `memberplus_drill` con el `pg_restore` de arriba. Y antes de cualquier import real, *Backup now*.

Un detalle que se descubrió en esa prueba y conviene tener presente: el dump es de la hora del schedule, así que `alembic_version` en la base restaurada es el del respaldo. Si `main` ya trae migraciones nuevas, el contenedor las aplica al arrancar (`alembic upgrade head`), pero conviene verlo en los logs y no suponerlo.

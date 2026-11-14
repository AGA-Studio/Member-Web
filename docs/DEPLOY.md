# Despliegue — Member-Web

El API se despliega como **imagen Docker** construida en GitHub Actions y publicada en **GHCR**. Coolify no construye nada: solo hace `docker pull` y arranca el contenedor.

**Estado actual (13 nov 2026).** Sirviendo en `https://api-memberplus.neyzt.org` (API) y `https://memberplus.neyzt.org` (frontend) — proyecto **Member+** de Coolify, imágenes `ghcr.io/aga-studio/member-web:latest` y `ghcr.io/aga-studio/member-plus-frontend:latest`, base `memberplus` en el PostgreSQL del mismo proyecto. **Mergear a `main` despliega**: el workflow *Image* publica la imagen y llama al deploy webhook de Coolify. No hay releases obligatorios y la demo **es** producción: un solo entorno.

| Host | Qué sirve |
|---|---|
| `memberplus.neyzt.org` | **Frontend** — desplegado (imagen `member-plus-frontend:latest`) |
| `api-memberplus.neyzt.org` | **API** — en producción desde el 12 nov 2026 |

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
11. [Respaldos de producción en Backblaze B2](#11-respaldos-de-producción-en-backblaze-b2)

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
   - **El backend NO va en `memberplus.neyzt.org`**: ese nombre es del frontend. El reparto es `memberplus.neyzt.org` → frontend y `api-memberplus.neyzt.org` → API.
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

   **El `resource_uuid` de la respuesta es la app que se desplegó**: si no es la de este repo, el secreto `COOLIFY_WEBHOOK` está apuntando a la otra app (pasó el 13 nov: el backend desplegaba el frontend y el suyo no). El webhook es **por app**; el token es el mismo para las dos. Sin `COOLIFY_WEBHOOK` el paso solo avisa y el deploy sigue siendo manual.

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
| `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` | — | Opcionales. Almacenamiento de imágenes; sin `S3_ENDPOINT_URL` la API funciona igual y `/logo/update` responde 503. Opciones (RustFS en Coolify o Cloudflare R2) en [STORAGE.md](STORAGE.md#8-producción) |
| `TURNSTILE_ENABLED` | `true` | Opcional, `false` por defecto. Exige Cloudflare Turnstile en el login. **Se crea al final**, después de desplegar el backend y el frontend con el widget (ver abajo) |
| `TURNSTILE_SECRET` | — | Secreto del widget «Member+ Login» de Cloudflare. Solo en las variables de Coolify, nunca en el repo ni en la wiki |
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

| Servicio | Imagen | Qué es |
|---|---|---|
| `db` | `postgres:18` | Base del stack (volumen `pgdata`) |
| `api` | `ghcr.io/aga-studio/member-web:${API_IMAGE_TAG:-0.0.1}` | API, la misma imagen que producción |
| `web` | `ghcr.io/aga-studio/member-plus-frontend:${WEB_IMAGE_TAG:-sha-local-stack}` | Frontend compilado con `API_INTERNAL_URL=http://api:8000` |

**Por qué el frontend usa una imagen `-stack` y no la normal.** El `rewrite` de `/api/*` se evalúa en `next build` y queda horneado en la imagen. La imagen de producción apunta a `https://api-memberplus.neyzt.org`, así que en localhost y sin internet el navegador intentaría llamar a producción. La imagen `-stack` se construye con el build-arg interno y **solo sirve para este compose**: no se despliega en Coolify. Se publica desde el workflow *Image* del repo del frontend con `workflow_dispatch` y la casilla `stack`; el run imprime el tag `sha-<7>-stack` — inmutable, ligado al commit, como el resto de las imágenes — y aquí se fija a mano con `WEB_IMAGE_TAG`, igual que el tag de versión en Coolify.

Con `pull_policy: missing` un `up` normal no refresca una imagen que ya está local: después de publicar un tag nuevo, correr `docker compose --profile stack pull`.

### Antes del ensayo (con internet)

Con el tag que imprimió el workflow en `WEB_IMAGE_TAG` (en `.env` o exportado en la sesión):

```bash
export WEB_IMAGE_TAG=sha-abc1234-stack   # el tag que imprimió el run del workflow
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

## 11. Respaldos de producción en Backblaze B2

Plan de recuperación (DRP) de la base de producción. La decisión está cerrada en la wiki (*Decisiones por validar*: «`pg_dump` diario + restic, con restauración probada») y el diseño completo está en *Servicios de terceros: Turnstile en el login y respaldos en B2*. **No hay código del API involucrado:** todo vive en el host, fuera del repo.

> Estado: ⬜ **pendiente de la primera corrida.** Falta crear el bucket y la clave en B2, correr el script una vez y probar la restauración. Esta sección se marca como hecha cuando la prueba de restauración pase.

```mermaid
flowchart LR
    CRON["cron del host<br/>10 3 * * *"] --> SH["~/backups/scripts/backup-memberplus.sh<br/>(reusa lib.sh: log, avisos, retención)"]
    SH -->|"lxc exec → pg_dump -Fc memberplus"| PG[("Postgres en coolify-vm")]
    SH --> STG["staging en /mnt/storage<br/>(1 día de dumps)"]
    STG -->|"restic backup"| B2[("b2:memberplus-restic:pg<br/>bucket y clave propios")]
```

| Pieza | Valor |
|-------|-------|
| Dump | `pg_dump -Fc` de la base `memberplus`, por `lxc exec` al contenedor de Postgres de `coolify-vm` |
| Script | `~/backups/scripts/backup-memberplus.sh` en el host (no está en este repo) |
| Repositorio restic | `b2:memberplus-restic:pg`, con bucket y clave de aplicación propios, separados de la cuenta personal |
| Cuándo | cron `10 3 * * *`, después del pipeline personal de las 02:30 |
| Retención | `--keep-daily 7 --keep-weekly 5 --keep-monthly 6`, y un día de dumps en staging |

**Por qué en el host y no dentro de Coolify.** El respaldo no debe vivir dentro de lo que respalda: `coolify-vm` es descartable (sin snapshots, su único rollback es `lxc copy`), su disco es pequeño y no tiene `/mnt/storage`, donde viven la caché y el staging de restic. Si el PaaS se reconstruye, la contraseña del repositorio y el binario tienen que sobrevivir fuera. Los backups nativos de Coolify no cuentan como respaldo de verdad (solo cubren la base, no cifran en el cliente y su restauración no queda probada); siguen sirviendo como conveniencia, por ejemplo el `pg_dump` manual antes de una migración destructiva de la [sección 6](#6-migraciones-y-datos). Se usa cron y no un timer de systemd porque es lo que se vio en clase y basta para el prototipo.

### Pasos pendientes (DevOps)

1. **B2:** crear el bucket privado `memberplus-restic` y una *application key* limitada a ese bucket. La clave y la contraseña de restic se guardan solo en el host (y en el gestor de contraseñas del equipo), nunca en el repo ni en la wiki.
2. **Inicializar el repositorio** restic `b2:memberplus-restic:pg` y correr el script una vez a mano.
3. **Agregar la línea de cron** `10 3 * * *` en el host.
4. **Probar la restauración** en una base desechable (nunca en `memberplus`):
   - restaurar el último snapshot con `restic restore latest` a un directorio temporal;
   - crear una base vacía y cargar el dump con `pg_restore --no-owner`;
   - comprobar que `alembic_version` coincide con producción y que los conteos de `businesses`, `users` y `customers` cuadran;
   - borrar la base desechable.
5. Guardar como evidencia para la Etapa 4 la salida de `restic snapshots` y el resultado de la restauración, y marcar el estado de esta sección como ✅.

### Cómo se verifica

| Qué | Cómo |
|-----|------|
| Los respaldos corren | `restic snapshots` muestra uno por día |
| La retención se aplica | `restic forget --dry-run` con la política de arriba no deja más de 7 diarios, 5 semanales y 6 mensuales |
| Se pueden usar | La restauración del paso 4 termina sin errores y los conteos cuadran |

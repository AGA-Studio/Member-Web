# CI — Member-Web

El proyecto se revisa en **GitHub Actions** con dos archivos: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) corre lint y pruebas en cada PR y cada push a `main`, sin secretos; [`.github/workflows/review.yml`](../.github/workflows/review.yml) comenta el PR contra la documentación (sección 11) y no bloquea.

> Arquitectura: [ARCHITECTURE.md](ARCHITECTURE.md) · Pruebas: [TESTING.md](TESTING.md) · Migraciones: [MIGRATIONS.md](MIGRATIONS.md)

## Índice

1. [Por qué](#1-por-qué)
2. [Los jobs](#2-los-jobs)
3. [Cuándo corre](#3-cuándo-corre)
4. [Cómo correr lo mismo en local](#4-cómo-correr-lo-mismo-en-local)
5. [Qué verifica el job de PostgreSQL](#5-qué-verifica-el-job-de-postgresql)
6. [Versiones fijadas](#6-versiones-fijadas)
7. [Cómo cambiar el workflow](#7-cómo-cambiar-el-workflow)
8. [Qué no cubre todavía](#8-qué-no-cubre-todavía)
9. [Problemas comunes](#9-problemas-comunes)
10. [Reglas](#10-reglas)
11. [Revisor automático de PRs](#11-revisor-automático-de-prs)

---

## 1. Por qué

| Antes | Ahora |
|---|---|
| Cada quien corría `ruff` y `pytest` cuando se acordaba | Los mismos comandos corren en cada PR |
| Una migración rota se descubría al desplegar | Se descubre en el PR, contra PostgreSQL real |
| GitHub no mostraba el error en la línea del código | `ruff` anota archivo y línea en el diff |
| El lock podía quedar desincronizado del `pyproject.toml` | `uv sync --locked` falla si eso pasa |

Lo que el CI **no** hace: desplegar, medir cobertura (pendiente) ni probar el frontend (vive en [su propio repo](https://github.com/AGA-Studio/Member-Plus-Frontend)).

---

## 2. Los jobs

Los tres corren en paralelo. Si uno falla, los demás siguen hasta terminar (no se cancelan entre sí).

| Job | Qué corre | Tiempo típico |
|-----|-----------|---------------|
| `lint` | `uv sync --locked`, `ruff check --output-format=github .`, `ruff format --check .` | ~8 s |
| `test` | `uv run pytest -q -rx` con el SQLite temporal de `tests/conftest.py` | ~22 s |
| `test (postgres)` | Servicio `postgres:18`, conexión real desde el engine, `pytest` con `TEST_DATABASE_URL`, y migraciones en una base aparte | ~38 s |

Los nombres de los jobs son lo que se marca como *required check* en GitHub, así que **no se renombran** sin avisar al equipo: si cambian, el PR se queda esperando un check que ya no existe.

---

## 3. Cuándo corre

```mermaid
flowchart LR
    PR["pull_request<br/>hacia main"] --> CI["CI"]
    PUSH["push a main"] --> CI
    MAN["workflow_dispatch<br/>(a mano)"] --> CI
    CI --> L["lint"]
    CI --> T["test (SQLite)"]
    CI --> P["test (postgres)"]
```

- `concurrency`: un push nuevo sobre la misma rama **cancela** el run anterior, para no gastar minutos en commits que ya quedaron atrás.
- `permissions: contents: read`: el workflow solo lee el repo. Si algún día necesita publicar algo, se agrega el permiso mínimo en ese job, no en todo el archivo.
- Los PR desde forks también corren, porque no hay secretos de por medio.

---

## 4. Cómo correr lo mismo en local

Antes de subir, esto tiene que pasar en tu máquina:

```bash
uv sync --locked                     # falla si uv.lock no corresponde al pyproject.toml
uv run ruff check .                  # mismo lint que el job
uv run ruff format --check .         # formato, sin modificar archivos
uv run pytest -q -rx                 # prueba por prueba; -rx muestra por qué falló un xfail
```

Y contra PostgreSQL, que es lo que hace el tercer job:

```bash
docker compose up -d db
TEST_DATABASE_URL=postgresql+psycopg://memberplus:memberplus@localhost:5433/memberplus_test uv run pytest -q -rx
```

Ojo: el CI usa el puerto **5432** dentro del runner y tu compose expone **5433** en la máquina. Es el mismo servidor, distinto puerto.

---

## 5. Qué verifica el job de PostgreSQL

`conftest.py` cae a SQLite cuando `TEST_DATABASE_URL` no está definida. Eso significa que un job mal configurado puede dar verde sin haber tocado PostgreSQL, así que el job comprueba cuatro cosas en orden:

```mermaid
flowchart TB
    A["1. Conectar al servicio<br/>select version()"] --> B["2. pytest con TEST_DATABASE_URL"]
    B --> C["3. ¿La suite creó tablas en Postgres?<br/>to_regclass('public.users')"]
    C --> D["4. Migraciones en base limpia<br/>alembic upgrade head"]
    D --> E["5. ¿Modelos y migraciones coinciden?<br/>alembic check"]
```

| Paso | Qué demuestra |
|------|----------------|
| Conectar al servicio | Que el driver y la URL funcionan; imprime la versión del servidor |
| `pytest` con `TEST_DATABASE_URL` | Que la suite completa pasa en PostgreSQL, no solo en SQLite |
| `to_regclass('public.users')` | Que fue **la suite** la que creó las tablas; si `conftest` volviera a fijar SQLite, la base estaría vacía y el paso falla |
| `alembic upgrade head` en `memberplus_migrate` | Que las migraciones aplican sobre una base vacía |
| `alembic check` | Que `models/` y `migrations/` no divergen: si alguien cambia un modelo y olvida la migración, esto se pone rojo |

Las migraciones van al final y en una base **distinta** a propósito. Si corrieran primero sobre `memberplus_test`, el paso 3 dejaría de probar nada: las tablas ya existirían por la migración y no por la suite.

---

## 6. Versiones fijadas

| Pieza | Versión | Cómo se sube |
|-------|---------|--------------|
| Python | 3.14 | Se cambia `PYTHON_VERSION` en el `env` del workflow y `requires-python` en `pyproject.toml` |
| uv | 0.11.26 | `version:` en los tres pasos `setup-uv` |
| `actions/checkout` | `@v7` | Tag mayor flotante: `v7` apunta siempre a la última `7.x` |
| `astral-sh/setup-uv` | `@v10.3.3` | **Versión exacta**: este repo no publica tag mayor (`v10` responde 404), así que hay que subir el número a mano |

Para ver la última versión disponible de una action:

```bash
gh api repos/astral-sh/setup-uv/releases/latest --jq .tag_name
gh api repos/actions/checkout/releases/latest --jq .tag_name
```

El runner no instala Python aparte: `setup-uv` lo baja con `uv` y cachea `uv.lock`, así que un run repetido tarda segundos en el paso de dependencias.

---

## 7. Cómo cambiar el workflow

`.github/workflows/` es **archivo compartido**: se avisa en el chat del equipo antes de tocarlo, igual que `pyproject.toml` o las migraciones. Es el único archivo del repo que puede dejar a todos los PRs en rojo a la vez.

Antes de subir un cambio:

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"   # que el YAML cargue
gh pr checks <número-del-PR>                                                 # los tres jobs en verde
```

Reglas:

- Un cambio de workflow entra en su **propio PR**, nunca mezclado con código. Si el workflow queda mal, se detecta y se revierte sin tocar la funcionalidad.
- Los pasos nuevos llevan un comentario que explica **qué previenen**, no qué hacen.
- Nada de `echo ::set-output` ni acciones sin mantener: si una action no se actualiza desde hace un año, se cambia o se hace el paso a mano.

---

## 8. Qué no cubre todavía

| Falta | Por qué importa | Dónde va |
|-------|-----------------|----------|
| Umbral de cobertura (`--cov-fail-under=60`) | `pytest-cov` ya está instalado y el MVP pide 60 %; hoy solo se mide a mano | Una línea en el job `test` |
| `dependabot.yml` | Las actions se actualizan a mano | `.github/dependabot.yml` |
| `docker compose up` desde cero | Es un criterio del MVP (≤ 3 min) | Job aparte, ahora que existe el `Dockerfile` |
| Pruebas de RLS | Se escribirán con las políticas, en su migración | Job `test (postgres)` |
| Entorno de staging | Solo hay una app en Coolify; `main` publica imagen y es la que se sirve | Segunda app en Coolify apuntando a un tag fijo, cuando el MVP esté en producción |

El despliegue ya no está en esta lista: lo cubre el workflow `image.yml` y está documentado en [DEPLOY.md](DEPLOY.md).


---

## 9. Problemas comunes

**`uv sync --locked` falla con "lockfile needs to be updated".**
Alguien cambió `pyproject.toml` sin correr `uv lock`. En local: `uv lock` y sube `uv.lock` en el mismo commit.

**`ruff format --check` falla pero el archivo "se ve bien".**
Falta el formato, no el lint: `uv run ruff format .` y revisa el diff antes de commitear.

**`test (postgres)` falla en "Verificar que la suite usó PostgreSQL".**
La suite no creó tablas en Postgres: casi siempre es que `conftest.py` dejó de leer `TEST_DATABASE_URL`, o que un `drop_all` falló antes. Mira el log del paso `pytest` en el mismo job.

**`alembic check` falla con "New upgrade operations detected".**
Los modelos cambiaron sin migración. Corre `uv run alembic revision --autogenerate -m "..."`, revisa el archivo generado (autogenerate se equivoca con enums y tipos propios) y súbelo en el mismo PR.

**El job de Postgres falla al crear `memberplus_migrate` porque ya existe.**
No debería pasar: cada run levanta un contenedor nuevo. Si pasa en local, borra la base con `DROP DATABASE memberplus_migrate`.

**Un job se queda "esperando" en el PR.**
Probablemente se renombró un job y el *required check* apunta al nombre viejo. Vuelve a poner el nombre o pide que se actualice la protección de la rama.

---

## 10. Reglas

- `main` está protegida por el ruleset **`protect-main`** (Settings → Rules → Rulesets), sin excepciones ni para administradores:
  - todo entra por PR (no hay push directo);
  - `lint`, `test` y `test (postgres)` deben salir en verde. El job `review` **no** es obligatorio: comenta, no decide;
  - la rama debe estar al día con la base: si otro PR se fusiona antes, GitHub muestra **Update branch** y los checks vuelven a correr;
  - no se pueden borrar las ramas ni hacer *force push*.
- El CI **no se salta**: un PR en rojo no se fusiona, ni con "es solo documentación".
- Si el CI falla por el entorno del runner y no por el código, se arregla el workflow en el mismo PR; no se deja el rojo para después.
- Los pasos que verifican algo (conexión, tablas, migraciones) **fallan** cuando no se cumple; nunca solo imprimen un aviso.
- Documentar aquí cualquier job nuevo: qué hace, cuánto tarda y qué previene.

---

## 11. Revisor automático de PRs

Workflow aparte: [`.github/workflows/review.yml`](../.github/workflows/review.yml). No es parte de `ci.yml` porque necesita un secreto y permiso de escritura, y porque **no debe bloquear**: si el revisor se cae, el PR sigue su curso.

### Qué hace

En cada PR hacia `main`, **una sola vez**: al abrirlo, al reabrirlo o cuando pasa de borrador a listo para revisión. Un push posterior no la repite —cuesta ~2.5 min y ~$0.003—, y la revisión se queda con la versión del PR que se revisó.

Para volver a revisar a mano:

```bash
# Cerrar y reabrir el PR, o desde Actions → review → Run workflow (pide el número de PR)
gh workflow run review.yml --field pr=23
```

El comentario se **actualiza en su lugar** si ya existe uno del revisor: reabrir un PR o correrlo a mano deja un comentario, no dos.

### Qué reporta y qué no

Solo cinco clases de problema, todas de criterio, no de estilo:

| Reporta | No reporta |
|---|---|
| Contradice una decisión cerrada de la wiki | Estilo, formato o nombres (eso es Ruff) |
| Resuelve una decisión **abierta** sin decirlo | `business_id` en schemas, `async`, forma de rutas (eso es `tests/rules/`) |
| Implementa algo fuera del MVP | Cobertura de pruebas, rendimiento, refactors |
| Toca un archivo compartido sin mencionarlo | Cualquier cosa que no esté en `docs/REVISION.md` |

Si no encuentra nada, lo dice en una línea. Nunca aprueba ni pide cambios formalmente: es un aviso para quien revisa, y su criterio manda.

### El secreto

Necesita `OPENCODE_API_KEY` en **Settings → Secrets and variables → Actions** del repositorio (o de la organización). Es la llave de OpenCode Go, la misma que usa el equipo para el modelo `deepseek-v4.1-flash`.

- Sin el secreto —por ejemplo en un PR desde un fork— el script no hace nada y sale con 0: el job queda verde sin comentario.
- El costo de una revisión ronda **$0.001–0.003** del cupo mensual de Go (unas 11 mil tokens de entrada). Diez PRs al día no llegan a dos centavos al mes.
- El razonamiento del modelo gasta el mismo `max_tokens` que la respuesta. Si se lo come entero (`finish=length`, contenido vacío), el script reintenta con más presupuesto: 8 mil, 16 mil y 24 mil tokens (`TOKEN_BUDGETS`). Con un PR grande (el #30 mandó ~22 mil tokens de entrada) los 12 mil de antes no alcanzaron. En el peor caso los tres intentos tardan unos 6 min, dentro de los 10 del job; cada llamada al modelo espera hasta 5 min (`MODEL_TIMEOUT`).

### Probar en local

```bash
gh pr diff 22 > /tmp/pr22.diff
export OPENCODE_API_KEY=...
uv run python -m scripts.review_pr --diff-file /tmp/pr22.diff --title "probar el revisor"
```

Imprime el comentario que publicaría, sin tocar GitHub.

### Cuando un hallazgo está mal

Gana el criterio de quien revisa. Si el revisor se equivoca dos veces con la misma regla, el error está en `docs/REVISION.md`: se corrige ahí y el siguiente PR ya lo ve. Si el error es del código, es un hallazgo real.

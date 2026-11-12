#!/bin/sh
# Arranque del contenedor: migra y luego sirve.
#
# El `&&` es deliberado: si una migración falla, la API NO arranca. Preferimos
# un contenedor caído (visible en Coolify) a uno sirviendo con esquema viejo.
#
# Rollback: si vuelves a una imagen anterior y la base ya está en una revisión
# más nueva, Alembic se niega a arrancar (no encuentra esa revisión). Eso es lo
# esperado: baja el esquema a mano con `alembic downgrade <rev>` o vuelve a
# desplegar hacia adelante. Nunca se revierte solo.
set -eu

echo "Aplicando migraciones..."
alembic upgrade head

echo "Arrancando uvicorn en el puerto ${PORT:-8000}..."
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips '*'

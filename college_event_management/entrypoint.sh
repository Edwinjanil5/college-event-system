#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "Applying database migrations..."
  flask --app wsgi:app db upgrade
fi

exec gunicorn \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  wsgi:app

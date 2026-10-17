#!/usr/bin/env sh
set -eu

if [ "$(id -u)" -eq 0 ]; then
    chown appuser:appuser /app/media
    exec setpriv --reuid=appuser --regid=appuser --init-groups "$0" "$@"
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"

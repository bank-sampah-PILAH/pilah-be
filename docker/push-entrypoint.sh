#!/usr/bin/env sh
set -eu

if [ "$(id -u)" -eq 0 ]; then
    exec setpriv --reuid=appuser --regid=appuser --init-groups "$0" "$@"
fi

exec python manage.py deliver_push

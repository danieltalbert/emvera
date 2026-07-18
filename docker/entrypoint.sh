#!/bin/sh
set -eu

# Migrations are opt-in because production platforms should normally run them
# as a one-off release command rather than from every web replica.
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  python manage.py migrate --noinput
fi

exec "$@"

# syntax=docker/dockerfile:1.7
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libpq is required by psycopg; curl-free health checks use Python's stdlib.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system emvera \
    && adduser --system --ingroup emvera --home /home/emvera emvera

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install --requirement requirements.txt

COPY --chown=emvera:emvera . .
COPY --chown=emvera:emvera --chmod=755 docker/entrypoint.sh /usr/local/bin/emvera-entrypoint

# Manifest-backed WhiteNoise assets are produced once at image-build time.
RUN DJANGO_SECRET_KEY=build-only-secret-not-used-at-runtime \
    DJANGO_DEBUG=False \
    python manage.py collectstatic --noinput

USER emvera
EXPOSE 8000

ENTRYPOINT ["emvera-entrypoint"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "core.wsgi:application"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz/', timeout=3)"

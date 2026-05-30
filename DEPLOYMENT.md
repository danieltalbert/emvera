# Deployment Guide

## Prerequisites

- Python 3.12+ (Django 6.0 requires it) or Docker.
- A populated `.env` file. Copy `.env.example` to `.env` and set, at minimum,
  `DJANGO_SECRET_KEY`. For production also set `DJANGO_DEBUG=False` and a real
  `DJANGO_ALLOWED_HOSTS`.

## Local / containerized run

```bash
cp .env.example .env        # set DJANGO_SECRET_KEY
docker compose up --build
```

This builds the app image, runs database migrations, serves the app with
gunicorn, and fronts it with nginx on http://localhost/. Collected static files
are shared from the app image to nginx via the `staticfiles` volume.

To run without Docker:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput      # for production/static serving
gunicorn core.wsgi:application --bind 0.0.0.0:8000
```

## Database

Emvera ships configured for **SQLite**, which needs no setup and is what the
Docker image and CI use. The `psycopg2-binary` driver is already in
`requirements.txt`, so moving to PostgreSQL only requires pointing
`DATABASES` at it in `core/settings.py`, for example:

```python
import os
if os.environ.get("POSTGRES_DB"):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
```

Then add a `postgres:15` service to `docker-compose.yml` and the matching
`POSTGRES_*` variables to `.env`.

## Required environment variables

See `.env.example` for the complete, annotated list. The essentials:

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | **Required.** Django cryptographic signing key. |
| `DJANGO_DEBUG` | `True`/`False`; keep `False` in production. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP for password reset / reminders (console backend if unset). |
| `DEFAULT_FROM_EMAIL` | From-address for outbound mail. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Enable SMS reminders. |
| `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` | Enable Plaid bank linking. |

## Scheduled tasks

Payment reminders are sent by a management command, suitable for a cron job or
scheduler:

```bash
python manage.py send_due_reminders
```

Plaid items can be re-synced with:

```bash
python manage.py plaid_resync
```

## CI/CD

`.github/workflows/ci-cd.yml` runs on every push and pull request: it checks for
missing migrations, applies migrations, runs the test suite, and lints with
flake8 (failing only on real errors; style issues are reported but
non-blocking). The `deploy` job runs on `main` and is a placeholder — wire it to
your platform of choice (Railway, Render, Fly.io, AWS, …).

## Rollback

- Redeploy the previous image tag / commit.
- Restore the previous database backup (or, with SQLite, the previous
  `db.sqlite3` file).

# Deployment Guide

The Docker image runs Django with Gunicorn and WhiteNoise. A production deployment also needs managed PostgreSQL, SMTP, HTTPS termination, secret storage, monitoring, and backups.

For the current AWS decision, cost boundary, and single-host sandbox preview, see [docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md). That preview is intentionally not the public-production topology described here.

## Required configuration

| Variable | Requirement |
| --- | --- |
| `DJANGO_SECRET_KEY` | Unique high-entropy value; never reuse the build/demo value |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated production hostnames |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | HTTPS origins that submit forms |
| `DATABASE_URL` | Managed PostgreSQL connection string |
| `EMAIL_HOST` and SMTP settings | Required so activation/reset tokens are delivered securely |
| `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL` | Verified sender addresses |
| `PLAID_TOKEN_ENCRYPTION_KEY` | Dedicated Fernet key; required whenever Plaid credentials are enabled |

Provider credentials such as Plaid and Twilio are optional unless those features are enabled.

## HTTPS hardening

After confirming the platform forwards the original protocol correctly, set:

```dotenv
DJANGO_DEBUG=False
DJANGO_TRUST_X_FORWARDED_PROTO=True
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=3600
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False
DJANGO_SECURE_HSTS_PRELOAD=False
```

Increase HSTS gradually only after verifying every affected hostname over HTTPS. Do not enable preload casually; it is intentionally difficult to reverse.

## Release sequence

```sh
python manage.py check --deploy --fail-level WARNING
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn --config gunicorn.conf.py core.wsgi:application
```

Run migrations once as a release task. Leave `RUN_MIGRATIONS` unset for normal production web replicas.

## Operational probes

- `GET /healthz/` confirms the web process is responding.
- `GET /readyz/` confirms the default database can answer a query.

The readiness response deliberately excludes hostnames, exception text, connection strings, and provider state.

## Go-live checklist

- [ ] CI succeeds on the exact release commit.
- [ ] `check --deploy --fail-level WARNING` succeeds in the production environment.
- [ ] Debug mode is off and a custom error page is visible.
- [ ] A fresh secret key and provider credentials come from a managed secret store.
- [ ] PostgreSQL uses encrypted connections, least-privilege credentials, automated backups, and a restore test.
- [ ] SMTP activation and password reset are verified end to end.
- [ ] Static files, health checks, logs, metrics, alerts, and error redaction are verified.
- [ ] Data retention, account deletion, privacy terms, and incident response have owners.
- [ ] Plaid tokens use the dedicated Fernet key and the documented re-encryption command has been tested against a backup.
- [ ] Shared rate limits protect login, registration, verification resend, and password reset.
- [ ] Load, concurrency, and abuse tests match the expected audience.
- [ ] Competition rankings are labeled casual until score validation is server-authoritative.
- [ ] A rollback and database-migration recovery plan is documented for the host.

Passing this checklist makes a specific deployment reviewable; it does not turn the sandbox prototype into a regulated financial product.

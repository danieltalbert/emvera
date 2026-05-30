# Emvera Architecture

## Overview

Emvera is a single Django project (`core`) composed of focused, loosely-coupled
apps. Data integration owns the canonical financial models; the other feature
apps build on top of them.

## Apps

- **core/** — Django settings, root URL configuration, and WSGI/ASGI entry
  points. Uses a custom user model (`accounts.CustomUser`).
- **accounts/** — authentication, registration, profile, guided onboarding, and
  two-factor authentication (TOTP/email/static via `django-otp`, QR codes via
  `qrcode`). The `require_2fa` helper gates sensitive views.
- **data_integration/** — the financial data layer. Models: `Account`,
  `Transaction`, `Investment`, `Debt`, and `PlaidItem`. Provides Plaid linking
  and sync (`plaid_client`, `plaid_sync`, and a `plaid_resync` management
  command), CSV import (`csv_import`), and manual entry forms. Plaid access
  tokens are encrypted at rest with Fernet (`crypto`).
- **debt_management/** — supplements the shared `Debt` model with `CreditScore`
  and `PaymentReminder`. Payoff math (avalanche, snowball, custom, consolidation)
  lives in `utils`; the `send_due_reminders` management command dispatches
  email/SMS reminders.
- **investments/** — portfolio overview/performance, projections,
  recommendations, and comparison, backed by `recommendation_utils` and
  `visualization_utils`.
- **competition/** — gamified savings competitions (models for competitions and
  participation) with lobby, dashboard, mini-game, and winner views.

## Data flow

1. A user registers and is guided through onboarding (verify email → set up 2FA
   → connect an account).
2. Accounts and transactions enter the system via Plaid, CSV import, or manual
   entry, and are stored by `data_integration`.
3. `debt_management` and `investments` read those shared models to power
   dashboards, payoff plans, reminders, and projections.
4. `competition` layers an engagement loop on top of users' savings activity.

## Configuration

- Settings are environment-driven and loaded from `.env` via `python-dotenv`.
  `DJANGO_SECRET_KEY` is required; see `.env.example` for the full list.
- The default database is SQLite (`core/settings.py`). A `psycopg2-binary`
  driver is bundled so the project can be pointed at Postgres — see
  `DEPLOYMENT.md`.
- Email falls back to the console backend unless `EMAIL_HOST` is set. SMS is
  inactive unless the `TWILIO_*` variables are present. Plaid is inactive unless
  `PLAID_CLIENT_ID` is set.

## Testing

Each feature app ships a `tests.py`. Run the full suite with
`python manage.py test`. CI runs migrations, the test suite, and flake8 (see
`.github/workflows/ci-cd.yml`).

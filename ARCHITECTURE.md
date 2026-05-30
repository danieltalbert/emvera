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
- **paper_trading/** — an in-app *simulated* brokerage (`PaperAccount`,
  `PaperPosition`, `PaperOrder`). Users trade with virtual cash priced by live
  market data. Decoupled from `competition` but ready to power it later. See
  "Optional integrations" below.

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

## Optional integrations (built, gated, awaiting a decision + keys)

Emvera keeps two "live investing" directions open. Both are fully wired but
**gated** — with no API keys they render an explainer and no-op gracefully, so
the app and test suite run with nothing configured. Each client lazily imports
its SDK and exposes `is_configured()`, mirroring the existing Plaid client.

1. **Link a real brokerage (SnapTrade)** — the "Plaid for brokerages." Reads a
   user's holdings from a brokerage they already have (Robinhood, Schwab,
   Fidelity, …). `snaptrade_client.py` does the API calls; `brokerage_sync.py`
   upserts the results into `Account`/`Investment`; `BrokerageLink` stores the
   per-user secret (encrypted). Keys: `SNAPTRADE_CLIENT_ID`,
   `SNAPTRADE_CONSUMER_KEY`.
2. **Live pricing + paper trading (Alpaca)** — `alpaca_client.py` provides
   market-data quotes (used by `pricing.py` to value holdings live) and paper
   orders (used by the `paper_trading` app's `execution.py`). Keys:
   `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` (`ALPACA_PAPER` defaults to True).

Why both, and why separate: SnapTrade can read *external* brokerages but isn't a
market-data/trading venue; Alpaca is a broker + market-data provider but cannot
read a user's external brokerage. They are complementary, so whichever product
direction is chosen later, the plumbing already exists. See each module's
docstring for the full rationale.

## Testing

Each feature app ships a `tests.py`. Run the full suite with
`python manage.py test`. CI runs migrations, the test suite, and flake8 (see
`.github/workflows/ci-cd.yml`).

# Emvera

Emvera is a personal-finance web application built with Django. It helps users
connect their financial accounts, manage and pay down debt strategically, track
investments, and stay motivated through savings competitions.

## Features

- **Accounts & security** — registration, login, profile management, and
  two-factor authentication (TOTP authenticator apps via QR code, plus email/
  static device support through `django-otp`). A guided onboarding flow walks
  new users through email verification, 2FA, and connecting their first account.
- **Data integration** — link banks through **Plaid**, import a CSV of
  transactions, or enter accounts, transactions, and debts manually. Plaid
  access tokens are encrypted at rest with Fernet (`cryptography`).
- **Debt management** — a debt dashboard, payoff planners (avalanche, snowball,
  and custom ordering), consolidation suggestions, payment reminders (email/SMS),
  and credit-score tracking.
- **Investments** — portfolio overview and performance, growth projections,
  recommendations, and side-by-side investment comparison.
- **Competition** — gamified savings competitions with a lobby, live dashboard,
  a mini-game, and a winner screen.

## Tech stack

- Python 3.12+ and Django 6.0 (Django 6 requires Python 3.12 or newer)
- Django REST Framework
- `django-otp` + `pyotp` + `qrcode` for two-factor authentication
- `cryptography` (Fernet) for encrypting Plaid tokens
- SQLite by default (a `psycopg2-binary` driver is included for Postgres)
- `gunicorn` for production serving; Docker + nginx for deployment

## Project layout

```
emvera/
├── core/               # Django project: settings, URLs, WSGI/ASGI
├── accounts/           # Custom user, auth, 2FA, onboarding, profile
├── data_integration/   # Plaid, CSV import, manual entry, encryption
├── debt_management/    # Payoff planners, reminders, credit score
├── investments/        # Projections, recommendations, performance
├── competition/        # Savings competitions + mini-game
├── templates/          # Shared + registration + competition templates
├── static/             # CSS and static assets
├── manage.py
└── requirements.txt
```

## Local setup

1. Use Python 3.12 or newer and create a virtual environment:
   ```bash
   python3.12 -m venv .venv && source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the environment template and fill in values (at minimum a
   `DJANGO_SECRET_KEY`):
   ```bash
   cp .env.example .env
   ```
4. Apply migrations and start the dev server:
   ```bash
   python manage.py migrate
   python manage.py runserver
   ```
5. Visit http://127.0.0.1:8000/.

> Emails (password reset, reminders) print to the console in development unless
> `EMAIL_HOST` is set. SMS reminders are only sent when the `TWILIO_*` variables
> are configured. Plaid is only enabled when `PLAID_CLIENT_ID` is set.

## Running with Docker

```bash
cp .env.example .env   # ensure DJANGO_SECRET_KEY is set
docker compose up --build
```

The app is then available at http://localhost/ (nginx → gunicorn).

## Tests

```bash
python manage.py test
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — apps, data model, and request flow.
- [DEPLOYMENT.md](DEPLOYMENT.md) — Docker, environment variables, CI/CD, and
  switching to Postgres.

# Engineering Status

Last reviewed: 2026-07-18

This file records current engineering boundaries, not a transcript of past automation runs. Completed work remains discoverable in Git history and pull requests.

## Release baseline

- Real email activation for new accounts.
- Confirmed TOTP device setup and per-session OTP verification.
- Owner-scoped manual entry, CSV ingestion, and Plaid synchronization.
- Plaid Item reassignment protection with regression coverage.
- Versioned Plaid token encryption with an independent key and rotation command.
- Environment-driven PostgreSQL, SMTP, proxy, cookie, and HTTPS settings.
- Gunicorn, WhiteNoise, Docker Compose, health/readiness probes, CI, and dependency audit.
- Public project landing page plus architecture, integration, demo, security, and deployment documentation.

## Required before a public launch

1. Choose a hosting platform and complete `DEPLOYMENT.md` against its real infrastructure.
2. Add durable background delivery, retry state, and provider reconciliation for reminders.
3. Add shared, deployment-grade throttling for login, registration, verification resend, and password-reset traffic.
4. Replace client-authored mini-game scores with a server-authoritative event model before presenting competition rankings as tamper-resistant.
5. Complete privacy, retention, account-deletion, incident-response, monitoring, backup, restore, load, and abuse reviews.
6. Decide whether Alpaca paper trading or ML experiments belong in a separately reviewed release; do not imply either is implemented on `main` today.

## Optional product work

- Persist portfolio-wide recommendations only after choosing an explicit recommendation target model.
- Turn responsive, keyboard-focus, and color-contrast browser checks into repeatable CI tooling.
- Add a public demo deployment only after repository-visibility and historical-secret review.

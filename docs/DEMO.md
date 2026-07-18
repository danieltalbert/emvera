# Interview Demo

The safest demonstration tells a clear engineering story in under ten minutes and does not depend on real financial data.

## Prepare once

1. Copy `.env.example` to the ignored `.env`.
2. Generate a fresh local `DJANGO_SECRET_KEY`.
3. Optionally add Plaid Sandbox credentials locally. Never paste them into chat or commit them.
4. Run `docker compose up --build`.
5. Open the application at `http://localhost:8000/` and Mailpit at `http://localhost:8025/`.

## Suggested walkthrough

1. **Public surface:** show the landing page and explain the sandbox/real-money boundary.
2. **Activation:** register a disposable demo account, open its message in Mailpit, and follow the activation link.
3. **TOTP:** scan the setup code with an authenticator, sign out, and demonstrate that a password alone does not create an authenticated session.
4. **Data ownership:** add a synthetic account or import a small synthetic CSV, then explain that posted owner IDs are never trusted.
5. **Plaid Sandbox:** connect a provider-supplied test institution and show server-side account/transaction synchronization.
6. **Analysis:** open the portfolio and debt views using synthetic balances; explain which recommendations are deterministic rules rather than ML predictions.
7. **Engineering proof:** show the CI workflow, focused ownership/auth tests, health probes, and architecture document.

## Fallback when Plaid is unavailable

Use manual entry or a synthetic CSV. The app intentionally presents Plaid as unconfigured when credentials are absent, so the rest of the demo remains complete and honest.

For the standard Plaid Sandbox flow, Plaid documents the public test username
`user_good` and password `pass_good`. Use those provider-supplied test values
inside Plaid Link; they are not your Plaid API credentials. See Plaid's
[Sandbox test-credentials guide](https://plaid.com/docs/sandbox/test-credentials/)
before the interview in case the provider changes its test flow.

## Claims to avoid

- Do not call the release a live trading platform.
- Do not imply Alpaca, Stripe, or predictive ML is present on `main`.
- Do not use a real bank login, real balances, or personally identifying transaction data.
- Do not expose `.env`, Mailpit messages, authenticator seeds, browser storage, or provider dashboards on a recorded screen.

## Thirty-second project description

> Emvera is a Django personal-finance prototype built around secure data boundaries. It supports email activation and real per-session TOTP, user-scoped manual and CSV ingestion, a Plaid Sandbox synchronization path, debt and portfolio analysis, and virtual competitions. I focused the release on reproducibility and honest capability boundaries, with regression tests and containerized deployment, before adding paper-trading or ML experimentation.

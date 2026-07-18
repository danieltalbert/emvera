# Security Policy

## Supported version

Security fixes target the latest commit on `main`. Older branches and prototypes are not supported deployment targets.

## Reporting a vulnerability

Please do not open a public issue containing exploit details, personal data, access tokens, or credentials. Use GitHub's private vulnerability-reporting or security-advisory flow for this repository. Include:

- the affected route, component, and commit;
- the smallest safe reproduction;
- the expected and observed behavior;
- any evidence that data crossed a user or trust boundary.

Do not test against accounts or infrastructure you do not own.

## Secrets

Runtime secrets belong in environment variables or a managed secret store. `.env`, Plaid credentials and access tokens, SMTP credentials, Twilio credentials, database URLs, and TOTP secrets must never be committed or pasted into issues, pull requests, screenshots, or chat transcripts.

If a secret is exposed, revoke or rotate it first; removing it from the latest commit is not sufficient because Git history is durable.

## Current demonstration boundary

The supported demonstration uses synthetic data and Plaid Sandbox. It does not place real brokerage orders or move money. Production access to financial providers requires a separate security, privacy, data-retention, and incident-response review.

# Integrations

## Status matrix

| Provider or path | Release status | Data boundary |
| --- | --- | --- |
| Plaid | Implemented for Sandbox demonstration | Link token in browser; access token server-side and encrypted at rest |
| SMTP | Implemented | Activation and reset links; production requires real SMTP credentials |
| Twilio | Optional reminder transport | Disabled unless all credentials are configured |
| CSV/manual entry | Implemented | Validated and restricted to the signed-in owner's accounts |
| Alpaca | Not in the shipping release | Paper-trading adapter remains a roadmap item |
| Stripe/payments | Not in the shipping release | No payment or money-movement code is claimed |

## Plaid Sandbox

Required environment variables:

```dotenv
PLAID_CLIENT_ID=
PLAID_SECRET=
PLAID_ENV=sandbox
PLAID_PRODUCTS=transactions
PLAID_REDIRECT_URI=
PLAID_TOKEN_ENCRYPTION_KEY=
PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=
```

Credentials must be entered locally in the ignored `.env` or in the deployment secret manager. Do not put them in source code, screenshots, pull requests, issue text, or chat. `PLAID_REDIRECT_URI` is only needed for OAuth institutions and must exactly match the provider configuration.

The implemented flow is:

1. an OTP-verified user requests a short-lived Link token;
2. Plaid Link returns a public token to the browser callback;
3. Django exchanges it server-side for an Item and access token;
4. ownership is checked before any existing Item can be updated;
5. account and transaction data is synchronized into user-scoped rows;
6. only a non-sensitive sync summary returns to the browser.

Generate the token key with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

To rotate it, put the current key in `PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS`,
set the new key as `PLAID_TOKEN_ENCRYPTION_KEY`, run
`python manage.py reencrypt_plaid_tokens --dry-run`, then run the command without
`--dry-run`. Remove the previous key only after the rewrite and backup checks
succeed. Legacy sandbox rows derived from `DJANGO_SECRET_KEY` remain readable
for this one-time migration path.

## Email

New accounts are inactive until the signed activation link is used. Production startup checks fail when email is left on the console or dummy backend. Configure `EMAIL_HOST`, port, TLS/SSL mode, credentials, and sender addresses through environment variables.

The Docker demo uses Mailpit, which captures messages locally at `http://localhost:8025/` without sending email to the public internet.

## Twilio

Twilio is optional. Reminders use it only when `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER` are configured. Sandbox/demo work should prefer email and synthetic recipients. Provider delivery guarantees and retry semantics are not part of the current release.

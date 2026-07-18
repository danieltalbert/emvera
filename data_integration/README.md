# Data Integration App

This app owns Emvera's account, transaction, holding, debt, CSV-import, and
Plaid Sandbox ingestion boundary. It is intentionally separate from the debt
and investment presentation layers so provider payloads are normalized before
domain features consume them.

## Models

- **Account**: a user-owned checking, savings, credit, investment, or debt account
- **Transaction**: an account-scoped imported or manually entered transaction
- **Investment**: an account-scoped holding snapshot
- **Debt**: an account-scoped balance and repayment inputs
- **PlaidItem**: a user-owned provider Item with an encrypted server-side token

## Ingestion paths

- Manual forms assign ownership server-side.
- CSV uploads validate encoding, headers, dates, finite decimal ranges, and the selected account's owner before bulk creation.
- Plaid Link tokens and public-token exchange happen through OTP-protected POST endpoints.
- Plaid Items cannot be reassigned when two users present the same provider Item identifier.
- Transaction sync is cursor-based and filters updates/removals through the signed-in owner.

## Configuration

See [`docs/INTEGRATIONS.md`](../docs/INTEGRATIONS.md) for current provider
status and environment variables. Provider secrets belong in the ignored
`.env` or a deployment secret manager, never in this app or its tests.

## Verification

```powershell
python manage.py test data_integration
```
